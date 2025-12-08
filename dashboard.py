from flask import Flask, render_template_string, send_from_directory, jsonify, abort
import sqlite3
import os
from pathlib import Path
from datetime import datetime

DB_PATH = "db.sqlite"
MATCH_DIR = Path("data/matches")
SUS_DIR = Path("suspects")

app = Flask(__name__)

INDEX_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Surveillance Dashboard</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh;
      padding: 20px;
    }

    .container {
      max-width: 1400px;
      margin: 0 auto;
      background: rgba(255, 255, 255, 0.95);
      border-radius: 20px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
      overflow: hidden;
    }

    .header {
      background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
      color: white;
      padding: 30px 40px;
      text-align: center;
      position: relative;
      overflow: hidden;
    }

    .header::before {
      content: '';
      position: absolute;
      top: -50%;
      left: -50%;
      width: 200%;
      height: 200%;
      background: repeating-linear-gradient(
        45deg,
        transparent,
        transparent 10px,
        rgba(255, 255, 255, 0.03) 10px,
        rgba(255, 255, 255, 0.03) 20px
      );
      animation: slide 20s linear infinite;
    }

    @keyframes slide {
      0% { transform: translate(0, 0); }
      100% { transform: translate(50px, 50px); }
    }

    h1 {
      font-size: 2.5em;
      font-weight: 700;
      margin-bottom: 10px;
      position: relative;
      text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
    }

    .subtitle {
      font-size: 1.1em;
      opacity: 0.9;
      position: relative;
    }

    .content {
      padding: 40px;
    }

    .section {
      margin-bottom: 50px;
    }

    .section-title {
      font-size: 1.8em;
      color: #2a5298;
      margin-bottom: 25px;
      padding-bottom: 15px;
      border-bottom: 3px solid #667eea;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .badge {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 5px 15px;
      border-radius: 20px;
      font-size: 0.6em;
      font-weight: 600;
    }

    .cards-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 25px;
    }

    .suspect-card {
      background: white;
      border-radius: 15px;
      overflow: hidden;
      box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
      transition: transform 0.3s ease, box-shadow 0.3s ease;
      border: 2px solid #f0f0f0;
    }

    .suspect-card:hover {
      transform: translateY(-5px);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
    }

    .card-image {
      width: 100%;
      height: 220px;
      object-fit: cover;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }

    .card-body {
      padding: 20px;
    }

    .card-title {
      font-size: 1.3em;
      font-weight: 600;
      color: #2a5298;
      margin-bottom: 8px;
    }

    .card-info {
      color: #666;
      font-size: 0.9em;
      margin-bottom: 15px;
    }

    .btn {
      display: inline-block;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 10px 20px;
      border-radius: 25px;
      text-decoration: none;
      font-weight: 600;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      border: none;
      cursor: pointer;
    }

    .btn:hover {
      transform: scale(1.05);
      box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      background: white;
      border-radius: 15px;
      overflow: hidden;
      box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
    }

    thead {
      background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
      color: white;
    }

    th {
      padding: 18px;
      text-align: left;
      font-weight: 600;
      font-size: 1em;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    td {
      padding: 15px 18px;
      border-bottom: 1px solid #f0f0f0;
    }

    tbody tr {
      transition: background-color 0.2s ease;
    }

    tbody tr:hover {
      background-color: #f8f9ff;
    }

    .table-thumb {
      width: 80px;
      height: 80px;
      object-fit: cover;
      border-radius: 10px;
      box-shadow: 0 3px 10px rgba(0, 0, 0, 0.2);
    }

    .status-new {
      display: inline-block;
      background: #ff6b6b;
      color: white;
      padding: 4px 12px;
      border-radius: 12px;
      font-size: 0.85em;
      font-weight: 600;
      animation: pulse 2s ease-in-out infinite;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.7; }
    }

    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: #999;
    }

    .empty-state-icon {
      font-size: 4em;
      margin-bottom: 20px;
      opacity: 0.3;
    }

    .stats-bar {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 20px;
      margin-bottom: 40px;
    }

    .stat-card {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 25px;
      border-radius: 15px;
      box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
    }

    .stat-value {
      font-size: 2.5em;
      font-weight: 700;
      margin-bottom: 5px;
    }

    .stat-label {
      font-size: 0.9em;
      opacity: 0.9;
      text-transform: uppercase;
      letter-spacing: 1px;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🔍 Surveillance Command Center</h1>
      <p class="subtitle">Real-time Face Recognition & Tracking System</p>
    </div>

    <div class="content">
      <div class="stats-bar">
        <div class="stat-card">
          <div class="stat-value">{{ suspects|length }}</div>
          <div class="stat-label">Enrolled Suspects</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ sightings|length }}</div>
          <div class="stat-label">Total Sightings</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ active_cameras }}</div>
          <div class="stat-label">Active Cameras</div>
        </div>
      </div>

      <div class="section">
        <h2 class="section-title">
          👤 Monitored Suspects
          <span class="badge">{{ suspects|length }}</span>
        </h2>

        {% if suspects %}
          <div class="cards-grid">
            {% for s in suspects %}
              <div class="suspect-card">
                <img src="{{ s.img_url }}" class="card-image" alt="{{ s.name }}">
                <div class="card-body">
                  <div class="card-title">{{ s.name }}</div>
                  <div class="card-info">ID: {{ s.suspect_id[:8] }}...</div>
                  <a href="/map/{{ s.suspect_id }}" class="btn" target="_blank">📍 View Movement Path</a>
                </div>
              </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="empty-state">
            <div class="empty-state-icon">👥</div>
            <h3>No Suspects Enrolled</h3>
            <p>Add suspect images to the <code>suspects/</code> folder and restart the system</p>
          </div>
        {% endif %}
      </div>

      <div class="section">
        <h2 class="section-title">
          📹 Recent Sightings
          <span class="badge">Latest {{ sightings|length }}</span>
        </h2>

        {% if sightings %}
          <table>
            <thead>
              <tr>
                <th>Snapshot</th>
                <th>Suspect</th>
                <th>Camera Location</th>
                <th>Camera ID</th>
                <th>Timestamp</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {% for s in sightings %}
                <tr>
                  <td>
                    {% if s.image_path %}
                      <img src="{{ s.image_path }}" class="table-thumb" alt="Snapshot">
                    {% else %}
                      <div class="table-thumb" style="background: #ddd;"></div>
                    {% endif %}
                  </td>
                  <td><strong>{{ s.suspect_name }}</strong></td>
                  <td>{{ s.cam }}</td>
                  <td>Camera {{ s.cam_no }}</td>
                  <td>{{ s.datetime }}</td>
                  <td>
                    {% if loop.index <= 5 %}
                      <span class="status-new">NEW</span>
                    {% endif %}
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% else %}
          <div class="empty-state">
            <div class="empty-state-icon">📹</div>
            <h3>No Sightings Recorded</h3>
            <p>Sightings will appear here when suspects are detected by cameras</p>
          </div>
        {% endif %}
      </div>
    </div>
  </div>
</body>
</html>
"""

MAP_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Suspect Movement Path - {{suspect_name}}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body, html { height: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }

    #map { 
      height: 100%; 
      width: 100%;
    }

    .topbar { 
      position: absolute; 
      z-index: 1000; 
      top: 20px; 
      left: 20px;
      background: rgba(255, 255, 255, 0.95);
      padding: 15px 25px;
      border-radius: 12px;
      box-shadow: 0 5px 20px rgba(0, 0, 0, 0.3);
      display: flex;
      align-items: center;
      gap: 15px;
    }

    .back-btn {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 10px 20px;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 600;
      transition: transform 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }

    .back-btn:hover {
      transform: scale(1.05);
    }

    .suspect-info {
      border-left: 3px solid #667eea;
      padding-left: 15px;
    }

    .suspect-name {
      font-size: 1.2em;
      font-weight: 700;
      color: #2a5298;
    }

    .suspect-id {
      font-size: 0.85em;
      color: #666;
    }

    .popup-img { 
      max-width: 220px; 
      height: auto; 
      display: block; 
      border-radius: 8px;
      margin-top: 10px;
    }

    .leaflet-popup-content {
      margin: 15px;
      line-height: 1.6;
    }

    .leaflet-popup-content h3 {
      margin: 0 0 8px 0;
      color: #2a5298;
    }

    .custom-marker {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      width: 30px;
      height: 30px;
      border-radius: 50%;
      border: 3px solid white;
      box-shadow: 0 3px 10px rgba(0, 0, 0, 0.3);
    }
  </style>
</head>
<body>
  <div class="topbar">
    <a href="/" class="back-btn">← Back to Dashboard</a>
    <div class="suspect-info">
      <div class="suspect-name">{{suspect_name}}</div>
      <div class="suspect-id">Tracking ID: {{suspect_id}}</div>
    </div>
  </div>
  <div id="map"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const suspect = "{{suspect_id}}";
    const apiUrl = "/api/suspect/" + suspect + ".geojson";

    const map = L.map('map').setView([13.6288, 79.4192], 13);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    fetch(apiUrl)
      .then(r => {
        if (!r.ok) throw new Error("No data available");
        return r.json();
      })
      .then(fc => {
        const features = fc.features || [];
        let pts = [];
        let markerCount = 0;

        features.forEach(f => {
          if (f.geometry.type === "LineString") {
            const coords = f.geometry.coordinates.map(c => [c[1], c[0]]);
            L.polyline(coords, {
              color: '#667eea',
              weight: 4,
              opacity: 0.7,
              dashArray: '10, 5'
            }).addTo(map);
            pts = pts.concat(coords);
          } else if (f.geometry.type === "Point") {
            const c = f.geometry.coordinates;
            const latlon = [c[1], c[0]];
            const props = f.properties || {};

            markerCount++;
            let popupHtml = `
              <h3>🎯 Sighting #${markerCount}</h3>
              <strong>Suspect:</strong> ${props.suspect_name}<br/>
              <strong>Camera:</strong> ${props.cam_no}<br/>
              <strong>Time:</strong> ${props.datetime}
            `;

            if (props.image_path) {
              const filename = props.image_path.split('/').pop();
              popupHtml += `<img class="popup-img" src="/matches/${filename}" />`;
            }

            const marker = L.marker(latlon, {
              icon: L.divIcon({
                className: 'custom-marker',
                html: `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:white;font-weight:bold;font-size:12px;">${markerCount}</div>`,
                iconSize: [30, 30]
              })
            }).addTo(map);

            marker.bindPopup(popupHtml);
            pts.push(latlon);
          }
        });

        if (pts.length > 0) {
          const bounds = L.latLngBounds(pts);
          map.fitBounds(bounds.pad(0.2));
        } else {
          alert("No geolocated sightings found for this suspect. Make sure camera locations are configured in surveillance.py");
        }
      })
      .catch(err => {
        alert("Unable to load tracking data: " + err.message);
      });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get suspects
    cur.execute("SELECT suspect_id, name, image_path FROM suspects")
    rows = cur.fetchall()
    suspects = []
    for sid, name, imgpath in rows:
        img_url = "/static/suspect/" + os.path.basename(imgpath) if imgpath else ""
        suspects.append({'suspect_id': sid, 'name': name, 'img_url': img_url})

    # Get sightings (latest 50)
    cur.execute("SELECT suspect_name, cam, cam_no, datetime, image_path FROM sightings ORDER BY datetime DESC LIMIT 50")
    rows = cur.fetchall()
    sightings = []
    for name, cam, camno, dt, imgpath in rows:
        img_url = "/matches/" + os.path.basename(imgpath) if imgpath else ""
        sightings.append({
            'suspect_name': name,
            'cam': cam,
            'cam_no': camno,
            'datetime': dt,
            'image_path': img_url
        })

    conn.close()

    # Calculate active cameras (simplified - you can enhance this)
    active_cameras = 4

    return render_template_string(INDEX_TEMPLATE,
                                  suspects=suspects,
                                  sightings=sightings,
                                  active_cameras=active_cameras)


@app.route('/static/suspect/<filename>')
def serve_suspect_image(filename):
    return send_from_directory(str(SUS_DIR), filename)


@app.route('/matches/<filename>')
def serve_match_image(filename):
    return send_from_directory(str(MATCH_DIR), filename)


@app.route("/api/suspect/<suspect_id>.geojson")
def suspect_geojson(suspect_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
                SELECT suspect_name, cam_no, datetime, image_path, lat, lon
                FROM sightings
                WHERE suspect_id = ?
                ORDER BY datetime ASC
                """, (suspect_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "no sightings"}), 404

    coord_list = []
    features = []

    for (sus_name, cam_no, dt, imgpath, lat, lon) in rows:
        if lat is not None and lon is not None:
            try:
                latf = float(lat)
                lonf = float(lon)
                coord_list.append([lonf, latf])

                props = {
                    "suspect_name": sus_name,
                    "cam_no": cam_no,
                    "datetime": dt,
                    "image_path": imgpath
                }

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lonf, latf]},
                    "properties": props
                })
            except (ValueError, TypeError):
                continue

    fc = {"type": "FeatureCollection", "features": []}

    if len(coord_list) >= 2:
        fc["features"].append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coord_list},
            "properties": {"suspect_id": suspect_id, "points": len(coord_list)}
        })

    fc["features"].extend(features)
    return jsonify(fc)


@app.route("/map/<suspect_id>")
def map_page(suspect_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM suspects WHERE suspect_id = ?", (suspect_id,))
    row = cur.fetchone()
    conn.close()

    suspect_name = row[0] if row else "Unknown"

    return render_template_string(MAP_HTML, suspect_id=suspect_id, suspect_name=suspect_name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)