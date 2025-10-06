# attendance_system.py
from database import FaceDatabase
import logging
from datetime import datetime, date
import excel_manager

db = FaceDatabase()

logging.basicConfig(filename='attendance.log', level=logging.INFO, format='%(asctime)s-%(message)s')

# Ensure excel files exist at start
excel_manager.init_excel_files()

def mark_attendance(user_id, name, write_to_excel=True):
    """
    Record attendance for a single user. Returns:
      True  -> newly marked
      False -> already marked today or error
    """
    try:
        today = date.today()
        existing = db.get_attendance_report(today)  # assumes this returns rows with name in index 0 (based on your provided code)
        present_today = any(record[0] == user_id for record in existing)

        if not present_today:
            db.record_attendance(user_id)
            logging.info(f"Marked attendance for {name}")
            if write_to_excel:
                excel_manager.record_attendance_excel(user_id, name, status="present", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return True
        else:
            logging.warning(f"{name} already marked today")
            return False
    except Exception as e:
        logging.error(f"Error marking attendance: {str(e)}")
        return False

def mark_attendance_batch(matches, write_to_excel=True):
    """
    matches: list of tuples (user_id, name)
    returns: dict with user_id -> 'marked'|'already'|'error'
    """
    results = {}
    for user_id, name in matches:
        try:
            ok = mark_attendance(user_id, name, write_to_excel=write_to_excel)
            results[user_id] = "marked" if ok else "already"
        except Exception as e:
            logging.error(f"Error marking batch attendance for {name}: {e}")
            results[user_id] = "error"
    # After batch marking, generate absentee list for today (CSV)
    try:
        excel_manager.write_daily_absentees(target_date=date.today().isoformat())
    except Exception as e:
        logging.error(f"Failed to write absentees list: {e}")
    return results

def load_known_faces():
    """Load encodings from database"""
    encodings_data = db.get_all_encodings()
    encodings = [data['encoding'] for data in encodings_data]
    names = [data['name'] for data in encodings_data]
    user_ids = [data['user_id'] for data in encodings_data]
    return encodings, names, user_ids
