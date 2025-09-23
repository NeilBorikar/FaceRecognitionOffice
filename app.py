# app.py
from flask import Flask, render_template, Response, jsonify, g, request, redirect, url_for, flash, send_file,send_from_directory
import cv2
import numpy as np
from attendance_system import load_known_faces, mark_attendance_batch
from database import FaceDatabase
import threading
import face_recognition
import logging
from datetime import datetime, timedelta, date
from functools import lru_cache
import time
from logging.handlers import RotatingFileHandler
import sqlite3
import excel_manager

# Initialize Flask app
app = Flask(__name__)
camera = cv2.VideoCapture(0)
app.config.update({
    'VIDEO_SOURCE': 0,
    'FACE_RECOGNITION_THRESHOLD': 0.6,
    'CACHE_TIMEOUT_MINUTES': 5,
    'FRAME_SKIP_RATE': 2,  # Process every Nth frame
    'SECRET_KEY': 'your_secret_key_here'
})

# Logging
handler = RotatingFileHandler('app.log', maxBytes=5*1024*1024, backupCount=2)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

# Global variables
current_frame = None
processing_lock = threading.Lock()
last_cache_clear = datetime.now()

# Ensure excel files exist
excel_manager.init_excel_files()

# Database connection helpers (reuse your FaceDatabase wrapper)
def get_db():
    if 'db' not in g:
        g.db = FaceDatabase()
        try:
            g.db._create_tables()
        except Exception as e:
            app.logger.error(f"Table creation failed: {str(e)}")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Caching known faces with LRU
@lru_cache(maxsize=1)
def get_cached_known_faces():
    app.logger.info("Loading known faces from database")
    return load_known_faces()

def clear_face_cache():
    global last_cache_clear
    now = datetime.now()
    if now - last_cache_clear > timedelta(minutes=app.config['CACHE_TIMEOUT_MINUTES']):
        get_cached_known_faces.cache_clear()
        last_cache_clear = now
        app.logger.info("Cleared face recognition cache")

# Video feed generator (yields MJPEG)
def generate_frames():
    global current_frame
    try:
        cap = cv2.VideoCapture(app.config['VIDEO_SOURCE'],cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise RuntimeError("Could not open camera")
    except Exception as e:
        app.logger.error(f"Camera initialization failed: {str(e)}")
        return

    frame_counter = 0
    try:
        while True:
            success, frame = cap.read()
            frame_counter += 1
            if not success:
                app.logger.warning("Frame capture failed")
                break

            # Frame skipping
            if frame_counter % app.config['FRAME_SKIP_RATE'] != 0:
                continue

            # Resize for faster face processing
            small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

            # Face detection + encodings
            face_locations = face_recognition.face_locations(rgb_small)
            face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

            # Use lock for current_frame and recognition
            with processing_lock:
                current_frame = frame.copy()
                known_encodings, known_names, user_ids = get_cached_known_faces()

                # If there are known encodings, compare
                if known_encodings:
                    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                        # distances against DB
                        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
                        if len(face_distances) == 0:
                            continue
                        best_idx = np.argmin(face_distances)
                        confidence = 1 - face_distances[best_idx]
                        if confidence > app.config['FACE_RECOGNITION_THRESHOLD']:
                            name = known_names[best_idx]
                            # scale back to full frame
                            top *= 4; right *= 4; bottom *= 4; left *= 4
                            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                            cv2.putText(frame, f"{name} ({confidence:.2f})", (left+6, bottom-6),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
                        else:
                            # Unknown face box
                            top *= 4; right *= 4; bottom *= 4; left *= 4
                            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 1)
                            cv2.putText(frame, "Unknown", (left+6, bottom-6),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

            # yield MJPEG frame
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    finally:
        try:
            cap.release()
        except Exception:
            pass
        app.logger.info("Camera resource released")

# Routes
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/video_feed')
def video_feed():
    clear_face_cache()
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/mark_attendance', methods=['POST', 'GET'])
def mark_attendance_endpoint():
    """
    Accepts a request to mark attendance from the current_frame.
    Handles multiple faces in the frame and marks all recognized employees.
    """
    try:
        clear_face_cache()

        with processing_lock:
            if current_frame is None:
                app.logger.error("No frame available for attendance marking")
                return jsonify({"status":"error","message":"Camera feed not available"}), 400

            small_frame = cv2.resize(current_frame, (0,0), fx=0.25, fy=0.25)
            rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_small)
            face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

            if not face_encodings:
                app.logger.warning("No faces detected in frame")
                return jsonify({"status":"error","message":"No face detected - please face the camera"}), 400

            known_encodings, known_names, user_ids = get_cached_known_faces()
            if not known_encodings:
                app.logger.error("No registered faces in database")
                return jsonify({"status":"error","message":"System has no registered users"}), 400

            matches = []  # (user_id, name)
            seen_user_ids = set()

            for enc in face_encodings:
                # compute distances to known faces
                distances = face_recognition.face_distance(known_encodings, enc)
                if len(distances) == 0:
                    continue
                best_idx = np.argmin(distances)
                confidence = 1 - distances[best_idx]
                if confidence > app.config['FACE_RECOGNITION_THRESHOLD']:
                    uid = user_ids[best_idx]
                    name = known_names[best_idx]
                    if uid not in seen_user_ids:
                        matches.append((uid, name))
                        seen_user_ids.add(uid)

            if not matches:
                return jsonify({"status":"error","message":"Recognition confidence too low for all faces"}), 400

            # Mark attendance for all matched users (returns dict)
            results = mark_attendance_batch(matches)
            response = {"status":"success","results":[]}
            for uid, name in matches:
                response["results"].append({
                    "user_id": uid,
                    "name": name,
                    "result": results.get(uid, "error")
                })

            # After marking, produce absent CSV for today and include filename in response
            try:
                abs_file = excel_manager.write_daily_absentees(target_date=date.today().isoformat())
                response["absentees_csv"] = abs_file
            except Exception as e:
                app.logger.error(f"Failed to write absentees CSV: {e}")

            return jsonify(response)

    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"status":"error","message":"Internal server error"}), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Register endpoint extended to accept salary and proxy; still uses face_recognition to extract encoding.
    """
    if request.method == 'POST':
        try:
            name = request.form['name']
            email = request.form.get('email')
            salary = request.form.get('salary')  # optional
            proxy = request.form.get('proxy')    # optional

            if 'image' not in request.files:
                return "No image uploaded", 400
            image = request.files['image']
            if image.filename == '':
                return "No selected image", 400

            # extract face encoding
            img = face_recognition.load_image_file(image)
            encodings = face_recognition.face_encodings(img)
            if not encodings:
                return "No face found in image", 400

            # Save to DB
            db = get_db()
            user_id = db.add_user(name, email, proxy=proxy, salary=salary)
            db.add_face_encoding(user_id, encodings[0])
            # Also save to Excel for payroll/export convenience
            excel_manager.add_or_update_employee(user_id, name, email=email, proxy=proxy, salary=salary)

            # clear cache so immediate recognition works
            get_cached_known_faces.cache_clear()

            return jsonify({"status": "success", "user_id": user_id})

        except Exception as e:
            app.logger.error(f"Registration failed: {e}")
            return f"Registration failed: {str(e)}", 500

    return send_from_directory('static', 'index.html')

@app.route('/attendance')
def view_attendance():
    try:
        db = get_db()
        filter_type = request.args.get('filter_type', 'single')
        date_param = request.args.get('date')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        query = '''
            SELECT u.name, a.timestamp 
            FROM attendance_records a
            JOIN users u ON a.user_id = u.user_id
        '''
        params = []

        if filter_type == 'single' and date_param:
            query += ' WHERE DATE(a.timestamp) = ?'
            params.append(date_param)
        elif filter_type == 'range' and start_date and end_date:
            query += ' WHERE DATE(a.timestamp) BETWEEN ? AND ?'
            params.extend([start_date, end_date])

        query += ' ORDER BY a.timestamp DESC'

        cursor = db.conn.cursor()
        cursor.execute(query, params)
        records = cursor.fetchall()

        formatted_records = []
        for name, timestamp in records:
            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S') if isinstance(timestamp, str) else timestamp
            formatted_records.append({
                'name': name,
                'timestamp': dt,
                'formatted_time': dt.strftime('%Y-%m-%d %H:%M')
            })

        return send_from_directory('static', 'index.html')


    except sqlite3.Error as e:
        app.logger.error(f"Database error: {str(e)}")
        flash('Database error occurred', 'danger')
        return redirect(url_for('index'))
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        flash('An unexpected error occurred', 'danger')
        return redirect(url_for('index'))

@app.route('/users')
def view_users():
    try:
        db = get_db()
        users = db.conn.execute('SELECT * FROM users').fetchall()
        return send_from_directory('static', 'index.html')

    except Exception as e:
        logging.error(f"Failed to fetch users: {str(e)}")
        return "Error loading user list", 500

@app.route('/download_employees')
def download_employees():
    try:
        return send_file('employees.xlsx', as_attachment=True)
    except Exception as e:
        app.logger.error(f"Failed to send employees.xlsx: {e}")
        return "Error", 500

@app.route('/download_attendance')
def download_attendance():
    try:
        return send_file('attendance.xlsx', as_attachment=True)
    except Exception as e:
        app.logger.error(f"Failed to send attendance.xlsx: {e}")
        return "Error", 500

@app.route('/health')
def health_check():
    return jsonify({"status":"healthy", "timestamp": datetime.now().isoformat()})


@app.route('/api/users')
def api_users():
    try:
        db = get_db()
        rows = db.conn.execute('SELECT user_id, name, email, proxy, salary, department, created_at FROM users ORDER BY user_id').fetchall()
        users = []
        for r in rows:
            users.append({
                "user_id": r[0],
                "name": r[1],
                "email": r[2],
                "proxy": r[3],
                "salary": r[4],
                "department": r[5],
                "created_at": r[6].isoformat() if hasattr(r[6], 'isoformat') else r[6]
            })
        return jsonify(users)
    except Exception as e:
        app.logger.error(f"API /api/users error: {e}")
        return jsonify([]), 500

@app.route('/api/attendance')
def api_attendance():
    try:
        filter_type = request.args.get('filter_type', 'single')
        date = request.args.get('date')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        cursor = get_db().conn.cursor()
        query = '''
            SELECT u.name, a.timestamp FROM attendance_records a
            JOIN users u ON a.user_id = u.user_id
        '''
        params = []
        if filter_type == 'single' and date:
            query += ' WHERE DATE(a.timestamp) = ?'
            params.append(date)
        elif filter_type == 'range' and start_date and end_date:
            query += ' WHERE DATE(a.timestamp) BETWEEN ? AND ?'
            params.extend([start_date, end_date])
        query += ' ORDER BY a.timestamp DESC'
        cursor.execute(query, params)
        rows = cursor.fetchall()
        records = [{"name": r[0], "timestamp": (r[1].isoformat() if hasattr(r[1], 'isoformat') else str(r[1]))} for r in rows]
        return jsonify(records)
    except Exception as e:
        app.logger.error(f"API /api/attendance error: {e}")
        return jsonify([]), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True, use_reloader=False)
