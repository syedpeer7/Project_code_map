"""
multi_cam_mosaic.py

Show multiple camera feeds in a single window (grid/mosaic). If a camera fails,
that cell is blank with "NO SIGNAL". All GUI calls are performed in the main thread.
"""

import cv2
import threading
import time
import math
import numpy as np

# === CONFIG ===
CAM_SOURCES = [
    0,
    "http://192.168.1.10:8080/video",
    "http://192.0.0.4:8080/video",
    "http://192.168.1.12:8080/video",
    "http://192.168.1.12:8080/video"
    # add more sources if needed
]

CELL_WIDTH = 320   # width of each camera cell in mosaic
CELL_HEIGHT = 240  # height of each camera cell in mosaic
GRID_COLS = None   # set to None to auto-calc (square-ish), or set an int
FPS = 20           # target display fps

# === Shared state ===
num_cams = len(CAM_SOURCES)
latest_frames = [None] * num_cams   # each entry: numpy array BGR or None
frame_locks = [threading.Lock() for _ in range(num_cams)]
stop_event = threading.Event()

def make_blank_cell(w, h, text="NO SIGNAL"):
    """Create blank (gray) image with centered text for offline cameras."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (40, 40, 40)  # dark gray
    # put label
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.7
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    x = max(10, (w - tw)//2)
    y = max(20, (h + th)//2)
    cv2.putText(img, text, (x, y), font, scale, (180,180,180), thickness, cv2.LINE_AA)
    return img

def capture_thread(cam_idx, source):
    """Thread: open capture and keep latest frame updated in latest_frames[cam_idx]."""
    cap = None
    backoff = 1.0
    while not stop_event.is_set():
        try:
            if cap is None:
                cap = cv2.VideoCapture(source)
                # tiny warmup
                time.sleep(0.5)

            ret, frame = cap.read()
            if not ret or frame is None:
                # mark as unavailable and attempt reconnect slowly
                with frame_locks[cam_idx]:
                    latest_frames[cam_idx] = None
                # release and retry after short backoff
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                time.sleep(backoff)
                # exponential backoff up to 5s
                backoff = min(5.0, backoff * 1.5)
                continue

            # Reset backoff when a frame is received
            backoff = 1.0

            # Optionally: annotate frame here (face boxes, labels...)
            # For example: cv2.putText(frame, f"Cam {cam_idx}", (10,20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

            # Resize to cell size to keep mosaic fast and consistent
            frame_to_publish = cv2.resize(frame, (CELL_WIDTH, CELL_HEIGHT), interpolation=cv2.INTER_AREA)

            with frame_locks[cam_idx]:
                latest_frames[cam_idx] = frame_to_publish

            # small sleep to yield CPU (capture rate controlled by camera source)
            time.sleep(0.001)
        except Exception as e:
            # On unexpected exception, mark as offline and try to recover
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
    # clean up
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass

def compose_mosaic(cells, cols, rows, cell_w, cell_h):
    """Given list of cell images (BGR or None), compose grid image."""
    # Ensure cells length = cols*rows; pad with blanks if necessary
    total = cols * rows
    b = make_blank_cell(cell_w, cell_h, text="NO SIGNAL")
    padded = []
    for i in range(total):
        if i < len(cells) and cells[i] is not None:
            padded.append(cells[i])
        else:
            padded.append(b.copy())

    # compose rows
    rows_img = []
    for r in range(rows):
        row_cells = padded[r*cols:(r+1)*cols]
        row_img = np.hstack(row_cells)
        rows_img.append(row_img)
    mosaic = np.vstack(rows_img)
    return mosaic

def main():
    global GRID_COLS
    # compute grid layout
    n = num_cams
    if GRID_COLS is None:
        cols = math.ceil(math.sqrt(n))
    else:
        cols = GRID_COLS
    rows = math.ceil(n / cols)

    # start capture threads
    threads = []
    for idx, src in enumerate(CAM_SOURCES):
        t = threading.Thread(target=capture_thread, args=(idx, src), daemon=True)
        t.start()
        threads.append(t)

    window_name = "MULTI-CAM MONITOR"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    # optional: set initial window size to show grid at 100% cell size
    cv2.resizeWindow(window_name, CELL_WIDTH * cols, CELL_HEIGHT * rows)

    desired_period = 1.0 / FPS
    try:
        while True:
            t0 = time.time()

            # collect current frames snapshot (copy under locks)
            cells = []
            for i in range(n):
                with frame_locks[i]:
                    frm = latest_frames[i]
                    if frm is None:
                        cells.append(None)
                    else:
                        cells.append(frm.copy())

            # compose mosaic
            mosaic = compose_mosaic(cells, cols, rows, CELL_WIDTH, CELL_HEIGHT)

            # optional: label each cell with camera index & 'NO SIGNAL' state
            # We'll draw small captions on top-left of each cell for clarity
            for i in range(n):
                r = i // cols
                c = i % cols
                x = c * CELL_WIDTH + 6
                y = r * CELL_HEIGHT + 20
                label = f"Cam {i}"
                if cells[i] is None:
                    label += " (offline)"
                cv2.putText(mosaic, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,200,255), 2)

            cv2.imshow(window_name, mosaic)

            # handle key
            k = cv2.waitKey(1) & 0xFF
            if k == ord('q'):
                break

            # maintain FPS
            elapsed = time.time() - t0
            to_wait = desired_period - elapsed
            if to_wait > 0:
                time.sleep(to_wait)

    except KeyboardInterrupt:
        print("[INFO] exiting")
    finally:
        stop_event.set()
        cv2.destroyAllWindows()
        # threads are daemon so process will exit; if you prefer join, join with timeout:
        for t in threads:
            t.join(timeout=0.5)

if __name__ == "__main__":
    main()
