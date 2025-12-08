import os
import time
import uuid
import sqlite3
import threading
import signal
import math
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

# === CONFIG ===
CAM_SOURCES = [
    0,  # local laptop webcam
    "http://192.168.1.10:8080/video",  # phone 1 (change to your phone IP)
    "http://192.0.0.4:8080/video",  # phone 2
    "http://192.168.1.12:8080/video"  # phone 3
]

# Camera GPS coordinates - UPDATE THESE with your actual camera locations
CAM_LOCATIONS = {
    0: (13.6288, 79.4192),  # Tirupati coordinates - update with actual cam location
    1: (13.6290, 79.4195),  # Example: slightly offset
    2: (13.6285, 79.4190),  # Example: slightly offset
    3: (13.6292, 79.4198)  # Example: slightly offset
}

DB_PATH = "db.sqlite"
MATCH_SNAPSHOT_DIR = Path("data/matches")
MATCH_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
SUSPECTS_DIR = Path("suspects")
FACE_THRESHOLD = 0.55
COOLDOWN_SECONDS = 60

# Mosaic display configuration
CELL_WIDTH = 320
CELL_HEIGHT = 240
GRID_COLS = None
FPS = 15


# === DB init ===
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
              CREATE TABLE IF NOT EXISTS suspects
              (
                  suspect_id
                  TEXT
                  PRIMARY
                  KEY,
                  name
                  TEXT,
                  image_path
                  TEXT,
                  embedding
                  BLOB
              )""")
    c.execute("""
              CREATE TABLE IF NOT EXISTS sightings
              (
                  id
                  TEXT
                  PRIMARY
                  KEY,
                  suspect_id
                  TEXT,
                  suspect_name
                  TEXT,
                  cam
                  TEXT,
                  cam_no
                  INTEGER,
                  datetime
                  TEXT,
                  image_path
                  TEXT,
                  lat
                  REAL,
                  lon
                  REAL
              )""")
    conn.commit()
    return conn


conn = init_db()

# === Face embedding backend ===
HAVE_INSIGHT = False
HAVE_FACE_REC = False
try:
    from insightface.app import FaceAnalysis

    face_app = FaceAnalysis(allowed_modules=['detection', 'recognition'])
    face_app.prepare(ctx_id=-1, det_size=(640, 640))
    HAVE_INSIGHT = True
    print("[INFO] Using InsightFace for face detection & embedding.")
except Exception as e:
    print("[WARN] InsightFace not available, falling back if face_recognition present.", e)
    try:
        import face_recognition

        HAVE_FACE_REC = True
        print("[INFO] Using face_recognition for embedding (fallback).")
    except Exception as e2:
        print("[ERROR] No face embedding backend available. Install insightface or face_recognition.", e2)


def face_embeddings_insight(bgr_img):
    faces = face_app.get(bgr_img)
    out = []
    for f in faces:
        bbox = f.bbox.astype(int).tolist()
        emb = np.array(f.embedding, dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-6)
        out.append((bbox, emb))
    return out


def face_embeddings_rec(bgr_img):
    rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
    locations = face_recognition.face_locations(rgb)
    if not locations:
        return []
    encodings = face_recognition.face_encodings(rgb, locations)
    out = []
    for (top, right, bottom, left), enc in zip(locations, encodings):
        bbox = [left, top, right, bottom]
        emb = np.array(enc, dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-6)
        out.append((bbox, emb))
    return out


def get_face_embeddings(bgr_img):
    if HAVE_INSIGHT:
        return face_embeddings_insight(bgr_img)
    elif HAVE_FACE_REC:
        return face_embeddings_rec(bgr_img)
    else:
        return []


# === Suspect gallery helpers ===
def bytes_from_vector(v: np.ndarray):
    return v.astype(np.float32).tobytes()


def vector_from_bytes(b: bytes):
    return np.frombuffer(b, dtype=np.float32)


def enroll_suspect(image_path: str, name: str):
    img = cv2.imread(image_path)
    if img is None:
        print("[WARN] could not read enroll image:", image_path)
        return None
    emb_list = get_face_embeddings(img)
    if not emb_list:
        print(f"[WARN] no face found in {image_path}, skipping.")
        return None
    bbox, emb = emb_list[0]
    sid = str(uuid.uuid4())
    c = conn.cursor()
    c.execute("INSERT INTO suspects(suspect_id, name, image_path, embedding) VALUES (?,?,?,?)",
              (sid, name, image_path, bytes_from_vector(emb)))
    conn.commit()
    print(f"[INFO] enrolled suspect {name} -> {sid}")
    return sid


def bulk_enroll(folder: Path):
    if not folder.exists():
        print("[INFO] suspects folder not found; create suspects/ and add images.")
        return
    for p in folder.iterdir():
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        name = p.stem
        cur = conn.cursor()
        cur.execute("SELECT suspect_id FROM suspects WHERE image_path = ?", (str(p),))
        if cur.fetchone():
            continue
        enroll_suspect(str(p), name)


def load_gallery():
    cur = conn.cursor()
    cur.execute("SELECT suspect_id,name,image_path,embedding FROM suspects")
    rows = cur.fetchall()
    gallery = []
    for sid, name, imgpath, emb_blob in rows:
        if emb_blob is None:
            continue
        emb = vector_from_bytes(emb_blob)
        gallery.append({'suspect_id': sid, 'name': name, 'image_path': imgpath, 'emb': emb})
    print(f"[INFO] Loaded {len(gallery)} suspects from DB.")
    return gallery


# === Matching helpers ===
def cos_sim(a: np.ndarray, b: np.ndarray):
    a = a / (np.linalg.norm(a) + 1e-6)
    b = b / (np.linalg.norm(b) + 1e-6)
    return float(np.dot(a, b))


def log_sighting(suspect, cam_name, cam_no, snapshot_path):
    sid = str(uuid.uuid4())
    dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Get camera location
    lat, lon = CAM_LOCATIONS.get(cam_no, (None, None))

    c = conn.cursor()
    c.execute("""INSERT INTO sightings(id, suspect_id, suspect_name, cam, cam_no, datetime, image_path, lat, lon)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (sid, suspect['suspect_id'], suspect['name'], cam_name, int(cam_no), dt, snapshot_path, lat, lon))
    conn.commit()
    print(f"[LOG] {suspect['name']} seen on {cam_name} (#{cam_no}) at {dt} - Location: ({lat}, {lon})")


# === Global state for threads & display ===
num_cams = len(CAM_SOURCES)
latest_frames = [None] * num_cams
frame_locks = [threading.Lock() for _ in range(num_cams)]
stop_event = threading.Event()
last_seen = {}


def make_blank_cell(w, h, text="NO SIGNAL"):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (40, 40, 40)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.7
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    x = max(10, (w - tw) // 2)
    y = max(20, (h + th) // 2)
    cv2.putText(img, text, (x, y), font, scale, (180, 180, 180), thickness, cv2.LINE_AA)
    return img


def capture_worker(cam_idx, source, gallery, face_threshold=FACE_THRESHOLD, cooldown=COOLDOWN_SECONDS):
    cam_name = f"cam{cam_idx}"
    print(f"[INFO] starting camera #{cam_idx} -> {source}")
    cap = None
    backoff = 1.0
    while not stop_event.is_set():
        try:
            if cap is None:
                cap = cv2.VideoCapture(source)
                time.sleep(0.5)
            ret, frame = cap.read()
            if not ret or frame is None:
                with frame_locks[cam_idx]:
                    latest_frames[cam_idx] = None
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                time.sleep(backoff)
                backoff = min(5.0, backoff * 1.5)
                continue
            backoff = 1.0

            fed = get_face_embeddings(frame)
            for bbox, emb in fed:
                best = None
                for s in gallery:
                    score = cos_sim(emb, s['emb'])
                    if best is None or score > best['score']:
                        best = {'suspect': s, 'score': score}
                if best is None:
                    continue

                if best['score'] >= face_threshold:
                    suspect = best['suspect']
                    key = (suspect['suspect_id'], cam_idx)
                    now_ts = time.time()
                    last = last_seen.get(key, 0.0)
                    if now_ts - last >= cooldown:
                        x1, y1, x2, y2 = map(int, bbox)
                        crop = frame[y1:y2, x1:x2].copy() if (x2 > x1 and y2 > y1) else frame.copy()
                        fn = MATCH_SNAPSHOT_DIR / f"{suspect['name']}_{cam_name}_{int(now_ts * 1000)}.jpg"
                        cv2.imwrite(str(fn), crop)
                        log_sighting(suspect, cam_name, cam_idx, str(fn))
                        last_seen[key] = now_ts
                        label = f"{suspect['name']} {best['score']:.2f}"
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
                        cv2.putText(frame, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
                    else:
                        x1, y1, x2, y2 = map(int, bbox)
                        label = f"{suspect['name']} (seen)"
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (180, 180, 0), 2)
                        cv2.putText(frame, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 0), 2)
                else:
                    x1, y1, x2, y2 = map(int, bbox)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (150, 150, 150), 2)
                    cv2.putText(frame, f"Unknown {best['score']:.2f}", (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                                0.5, (150, 150, 150), 2)

            try:
                frame_pub = cv2.resize(frame, (CELL_WIDTH, CELL_HEIGHT), interpolation=cv2.INTER_AREA)
            except Exception:
                frame_pub = cv2.resize(frame.copy(), (CELL_WIDTH, CELL_HEIGHT), interpolation=cv2.INTER_AREA)

            with frame_locks[cam_idx]:
                latest_frames[cam_idx] = frame_pub

            time.sleep(0.001)

        except Exception as e:
            print(f"[WARN] capture thread {cam_idx} error: {e}")
            with frame_locks[cam_idx]:
                latest_frames[cam_idx] = None
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
            time.sleep(1.0)

    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
    print(f"[INFO] stopped camera #{cam_idx}")


def compose_mosaic(cells, cols, rows, cell_w, cell_h):
    total = cols * rows
    blank = make_blank_cell(cell_w, cell_h, text="NO SIGNAL")
    padded = []
    for i in range(total):
        if i < len(cells) and cells[i] is not None:
            padded.append(cells[i])
        else:
            padded.append(blank.copy())
    rows_img = []
    for r in range(rows):
        row_cells = padded[r * cols:(r + 1) * cols]
        row_img = np.hstack(row_cells)
        rows_img.append(row_img)
    mosaic = np.vstack(rows_img)
    return mosaic


if __name__ == "__main__":
    bulk_enroll(SUSPECTS_DIR)
    gallery = load_gallery()
    if not gallery:
        print("[WARN] No suspects in DB. Put images into suspects/ and restart to enroll.")

    n = num_cams
    if GRID_COLS is None:
        cols = math.ceil(math.sqrt(n))
    else:
        cols = GRID_COLS
    rows = math.ceil(n / cols)

    threads = []
    for idx, src in enumerate(CAM_SOURCES):
        t = threading.Thread(target=capture_worker, args=(idx, src, gallery), daemon=True)
        t.start()
        threads.append(t)


    def _handle_sigint(sig, frame):
        print("[INFO] received stop signal")
        stop_event.set()


    signal.signal(signal.SIGINT, _handle_sigint)

    window_name = "MULTI-CAM MONITOR"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(window_name, CELL_WIDTH * cols, CELL_HEIGHT * rows)

    desired_period = 1.0 / FPS
    try:
        while True:
            t0 = time.time()

            cells = []
            for i in range(n):
                with frame_locks[i]:
                    frm = latest_frames[i]
                    if frm is None:
                        cells.append(None)
                    else:
                        cells.append(frm.copy())

            mosaic = compose_mosaic(cells, cols, rows, CELL_WIDTH, CELL_HEIGHT)

            for i in range(n):
                r = i // cols
                c = i % cols
                x = c * CELL_WIDTH + 6
                y = r * CELL_HEIGHT + 20
                label = f"Cam {i}"
                if cells[i] is None:
                    label += " (offline)"
                cv2.putText(mosaic, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

            cv2.imshow(window_name, mosaic)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            elapsed = time.time() - t0
            to_wait = desired_period - elapsed
            if to_wait > 0:
                time.sleep(to_wait)

    except KeyboardInterrupt:
        print("[INFO] exiting")
    finally:
        stop_event.set()
        time.sleep(0.3)
        cv2.destroyAllWindows()