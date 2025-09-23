"""
excel_manager.py
Excel integration for employees and attendance:

- employees.xlsx: master sheet for user metadata (user_id,name,email,proxy,salary,department)
- attendance.xlsx: chronological attendance log (date,user_id,name,status,time)
- absentees_YYYY-MM-DD.csv: daily generated absence report
- sync_db_to_excel(db): pull users from DB and overwrite employees.xlsx (safe temp-file write)

Uses pandas + openpyxl. Writes to temp files and atomically replaces target to minimize corruption.
"""

import os
import tempfile
import shutil
from datetime import datetime, date
from typing import Optional
import pandas as pd
import logging

logger = logging.getLogger("ExcelManager")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)


EXCEL_ENGINE = "openpyxl"

EMPLOYEES_FILE = "employees.xlsx"
ATTENDANCE_FILE = "attendance.xlsx"
SALARY_FILE = "salary.xlsx"
ABSENTEES_FILE = "absentees.xlsx"


def _safe_write_dataframe(df: pd.DataFrame, path: str):
    """
    Write DataFrame to an Excel file atomically (write to temp and move).
    """
    dir_name = os.path.dirname(os.path.abspath(path)) or "."
    base = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(prefix=base + ".",suffix=".xlsx", dir=dir_name)
    os.close(fd)
    try:
        df.to_excel(tmp_path, index=False, engine=EXCEL_ENGINE)
        # replace
        shutil.move(tmp_path, path)
        logger.info(f"Wrote {path} safely")
    except Exception as e:
        logger.exception(f"Failed writing Excel to {path}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def init_excel_files():
    # Employees
    if not os.path.exists(EMPLOYEES_FILE):
        df = pd.DataFrame(columns=["user_id", "name", "email", "proxy", "salary", "department", "created_at"])
        _safe_write_dataframe(df, EMPLOYEES_FILE)

    # Attendance
    if not os.path.exists(ATTENDANCE_FILE):
        df = pd.DataFrame(columns=["user_id", "name", "timestamp"])
        _safe_write_dataframe(df, ATTENDANCE_FILE)

    # Salary
    if not os.path.exists(SALARY_FILE):
        df = pd.DataFrame(columns=["user_id", "name", "salary", "last_updated"])
        _safe_write_dataframe(df, SALARY_FILE)

    # Absentees
    if not os.path.exists(ABSENTEES_FILE):
        df = pd.DataFrame(columns=["date", "user_id", "name", "reason"])
        _safe_write_dataframe(df, ABSENTEES_FILE)


def add_or_update_employee(user_id: int, name: str, email: Optional[str] = None,
                           proxy: Optional[str] = None, salary: Optional[float] = None,
                           department: Optional[str] = None, created_at: Optional[str] = None):
    """
    Upsert employee row in employees.xlsx based on user_id.
    """
    init_excel_files()
    df = pd.read_excel(EMPLOYEES_FILE, engine=EXCEL_ENGINE)
    # ensure user_id column exists and dtype consistent
    if "user_id" not in df.columns:
        df["user_id"] = pd.Series(dtype=int)
    mask = df["user_id"] == user_id
    if mask.any():
        idx = df.index[mask][0]
        df.at[idx, "name"] = name
        if email is not None: df.at[idx, "email"] = email
        if proxy is not None: df.at[idx, "proxy"] = proxy
        if salary is not None: df.at[idx, "salary"] = salary
        if department is not None: df.at[idx, "department"] = department
    else:
        row = {
            "user_id": user_id,
            "name": name,
            "email": email or "",
            "proxy": proxy or "",
            "salary": salary if salary is not None else "",
            "department": department or "",
            "created_at": created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _safe_write_dataframe(df, EMPLOYEES_FILE)


def record_attendance_excel(user_id: int, name: str, status: str = "present", timestamp: Optional[str] = None):
    """
    Append a single attendance event to attendance.xlsx
    status: 'present' or 'absent' or other custom status.
    """
    init_excel_files()
    timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = pd.read_excel(ATTENDANCE_FILE, engine=EXCEL_ENGINE)
    row = {"date": timestamp.split(" ")[0], "user_id": user_id, "name": name, "status": status, "time": timestamp}
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _safe_write_dataframe(df, ATTENDANCE_FILE)


def write_daily_absentees(target_date: Optional[str] = None, output_prefix: str = "absentees_") -> str:
    """
    Generate CSV of absentees for the target_date.
    Returns path to CSV file.
    """
    init_excel_files()
    target_date = target_date or date.today().isoformat()
    emp_df = pd.read_excel(EMPLOYEES_FILE, engine=EXCEL_ENGINE)
    att_df = pd.read_excel(ATTENDANCE_FILE, engine=EXCEL_ENGINE)

    # Determine present ids
    if "date" in att_df.columns and "status" in att_df.columns:
        present_mask = (att_df["date"] == target_date) & (att_df["status"].str.lower() == "present")
        present_ids = set(att_df.loc[present_mask, "user_id"].tolist())
    else:
        present_ids = set()

    all_ids = set(emp_df["user_id"].tolist()) if "user_id" in emp_df.columns else set()
    absentees = sorted(list(all_ids - present_ids))
    if not absentees:
        out_df = pd.DataFrame(columns=["user_id", "name", "email", "proxy", "salary", "department"])
    else:
        out_df = emp_df[emp_df["user_id"].isin(absentees)][["user_id", "name", "email", "proxy", "salary", "department"]]

    out_filename = f"{output_prefix}{target_date}.csv"
    out_df.to_csv(out_filename, index=False)
    logger.info(f"Wrote absentees CSV: {out_filename}")
    return out_filename


def get_all_employees_df() -> pd.DataFrame:
    init_excel_files()
    return pd.read_excel(EMPLOYEES_FILE, engine=EXCEL_ENGINE)


def get_attendance_df() -> pd.DataFrame:
    init_excel_files()
    return pd.read_excel(ATTENDANCE_FILE, engine=EXCEL_ENGINE)


def sync_db_to_excel(db):
    """
    Pull all users from FaceDatabase and overwrite employees.xlsx.
    db: instance of FaceDatabase (must implement list_users()).
    This function does NOT export encodings into Excel (encodings belong in DB).
    """
    init_excel_files()
    users = db.list_users()
    if not users:
        df = pd.DataFrame(columns=["user_id", "name", "email", "proxy", "salary", "department", "created_at"])
    else:
        df = pd.DataFrame(users)
        # keep only expected columns (fill missing)
        cols = ["user_id", "name", "email", "proxy", "salary", "department", "created_at"]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
    _safe_write_dataframe(df, EMPLOYEES_FILE)
    logger.info("Synchronized DB users to employees.xlsx")


def sync_excel_attendance_to_db(db):
    """
    Read attendance.xlsx and write any rows missing into DB.attendance_records.
    Use this if you sometimes record attendance in Excel and want to push to DB.
    WARNING: Idempotence: this implementation will check by exact timestamp and user_id to avoid duplicates.
    """
    df = get_attendance_df()
    if df.empty:
        return 0

    added = 0
    for _, row in df.iterrows():
        try:
            user_id = int(row["user_id"])
            timestamp = row["time"]
            # Check if such timestamp exists already in DB for user (simple existence check).
            # We do a naive approach: fetch attendance for that date and check exact timestamps.
            date_part = str(timestamp).split(" ")[0]
            db_rows = db.get_attendance_for_date(date_part)
            exists = any(str(r["user_id"]) == str(user_id) and str(r["timestamp"]) == str(timestamp) for r in db_rows)
            if not exists:
                # convert timestamp string to datetime if necessary
                if isinstance(timestamp, str):
                    try:
                        ts_val = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        ts_val = None
                else:
                    ts_val = timestamp
                if ts_val:
                    db.record_attendance(user_id, when=ts_val)
                    added += 1
        except Exception:
            logger.exception("Failed to sync a row from Excel to DB; skipping.")
            continue
    logger.info(f"Synced {added} attendance rows from Excel to DB")
    return added
