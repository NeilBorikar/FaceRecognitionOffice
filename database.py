"""
database.py
Robust SQLite-backed FaceDatabase for face-recognition attendance systems.

Features:
- Per-method DB connections (safer for threads).
- WAL journal mode + busy timeout to improve concurrent access.
- Tables: users, face_encodings, attendance_records (with foreign keys).
- Encodings serialized safely (pickle with highest protocol).
- CRUD: add/update/delete users, add multiple encodings per user.
- Attendance recording and flexible reporting (grouped by user_id).
- Defensive programming + logging.
"""

import sqlite3
import pickle
import threading
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("FaceDatabase")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)


class FaceDatabase:
    def __init__(self, db_path: str = "face_recognition.db", busy_timeout: int = 5000):
        """
        :param db_path: SQLite database file path
        :param busy_timeout: sqlite busy timeout in milliseconds
        """
        self.db_path = db_path
        self._write_lock = threading.Lock()  # serialize writes for safety
        # Ensure DB & tables exist
        with self._get_conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")         # better concurrency
            conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout)};")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._create_tables(conn)
            self._migrate_schema(conn)

    def _get_conn(self) -> sqlite3.Connection:
        """
        Return a new sqlite3.Connection configured for our use.
        NOTE: each call returns a fresh connection; callers should use context manager.
        """
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
            isolation_level=None,  # autocommit off, but we'll manage transactions explicitly
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _create_tables(self, conn: sqlite3.Connection):
        """Create tables if missing."""
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                email       TEXT UNIQUE,
                proxy       TEXT,
                salary      REAL,
                department  TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS face_encodings (
                encoding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                encoding    BLOB NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance_records (
                record_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            """
        )
        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_face_enc_user ON face_encodings(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_att_user_time ON attendance_records(user_id, timestamp);")
        conn.commit()
        cur.close()
   

    def _migrate_schema(self, conn: sqlite3.Connection):
        """Add missing columns to users if DB was created with an older schema."""
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users);")
        cols = {row["name"] for row in cur.fetchall()}

        added = []

        if "proxy" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN proxy TEXT;")
            added.append("proxy TEXT")
        if "salary" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN salary REAL;")
            added.append("salary REAL")
        if "department" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN department TEXT;")
            added.append("department TEXT")
        if "created_at" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
            added.append("created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        conn.commit()
        cur.close()

        if added:
            logger.info(f"DB schema migrated: added columns -> {', '.join(added)}")
        else:
            logger.info("DB schema up-to-date; no columns added.")

    # ---------------------------
    # User management
    # ---------------------------
    def add_user(self, name: str, email: Optional[str] = None,
                 proxy: Optional[str] = None, salary: Optional[float] = None,
                 department: Optional[str] = None) -> int:
        """
        Insert a new user. Returns user_id.
        """
        with self._write_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (name, email, proxy, salary, department) VALUES (?, ?, ?, ?, ?);",
                (name, email, proxy, salary, department),
            )
            user_id = cur.lastrowid
            conn.commit()
            cur.close()
            logger.info(f"Added user {name} (id={user_id})")
            return user_id

    def update_user(self, user_id: int, **fields) -> bool:
        """
        Update provided user fields. Usage: update_user(5, name='New Name', salary=20000)
        Returns True if updated (rows affected > 0).
        """
        if not fields:
            return False
        valid_cols = {"name", "email", "proxy", "salary", "department"}
        to_set = []
        params = []
        for k, v in fields.items():
            if k in valid_cols:
                to_set.append(f"{k} = ?")
                params.append(v)
        if not to_set:
            return False
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(to_set)} WHERE user_id = ?;"
        with self._write_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            changed = cur.rowcount
            conn.commit()
            cur.close()
            logger.info(f"Updated user {user_id}: {fields}")
            return changed > 0

    def delete_user(self, user_id: int) -> bool:
        """Delete user (encodings and attendance cascade)."""
        with self._write_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM users WHERE user_id = ?;", (user_id,))
            deleted = cur.rowcount
            conn.commit()
            cur.close()
            logger.info(f"Deleted user_id={user_id}")
            return deleted > 0

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Return user row as dict or None."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?;", (user_id,))
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        """Return list of users as dictionaries."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users ORDER BY user_id;")
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]

    # ---------------------------
    # Face encodings
    # ---------------------------
    def _serialize_encoding(self, encoding) -> bytes:
        """Serialize encoding using pickle (highest protocol)."""
        try:
            # We expect encoding to be a list/ndarray of floats
            return pickle.dumps(encoding, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            logger.exception("Failed to serialize encoding")
            raise

    def _deserialize_encoding(self, blob: bytes):
        """Deserialize encoding blob to original object (list/np.array)."""
        try:
            return pickle.loads(blob)
        except Exception as e:
            logger.exception("Failed to deserialize encoding")
            raise

    def add_face_encoding(self, user_id: int, encoding) -> int:
        """
        Add one encoding for the user. Returns encoding_id.
        Use multiple calls to add multiple encodings per user (good for multiple images).
        """
        blob = self._serialize_encoding(encoding)
        with self._write_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO face_encodings (user_id, encoding) VALUES (?, ?);",
                (user_id, sqlite3.Binary(blob))
            )
            eid = cur.lastrowid
            conn.commit()
            cur.close()
            logger.info(f"Stored encoding for user_id={user_id} (encoding_id={eid})")
            return eid

    def get_all_encodings(self) -> List[Dict[str, Any]]:
        """
        Return list of dicts:
         [{'user_id': int, 'name': str, 'encoding': <py object>}, ...]
        All encodings (many per user) are returned. For recognition, client can aggregate encodings.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT u.user_id AS user_id, u.name AS name, fe.encoding AS encoding_blob
                FROM face_encodings fe
                JOIN users u ON fe.user_id = u.user_id;
                """
            )
            rows = cur.fetchall()
            cur.close()
            result = []
            for r in rows:
                try:
                    enc = self._deserialize_encoding(r["encoding_blob"])
                except Exception:
                    continue
                result.append({"user_id": r["user_id"], "name": r["name"], "encoding": enc})
            return result

    def delete_encodings_for_user(self, user_id: int) -> int:
        """Delete all encodings for a user. Returns number deleted."""
        with self._write_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM face_encodings WHERE user_id = ?;", (user_id,))
            deleted = cur.rowcount
            conn.commit()
            cur.close()
            logger.info(f"Deleted {deleted} encodings for user_id={user_id}")
            return deleted

    # ---------------------------
    # Attendance
    # ---------------------------
    def record_attendance(self, user_id: int, when: Optional[datetime] = None) -> int:
        """
        Insert attendance row. Returns record_id.
        If when is provided, uses that timestamp.
        """
        when_val = when or datetime.now()
        with self._write_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO attendance_records (user_id, timestamp) VALUES (?, ?);",
                (user_id, when_val)
            )
            rid = cur.lastrowid
            conn.commit()
            cur.close()
            logger.info(f"Recorded attendance user_id={user_id} record_id={rid}")
            return rid

    def get_attendance_report(self, target_date: Optional[str] = None) -> List[Tuple[int, str, int]]:
        """
        Returns list of tuples (user_id, name, attendance_count) grouped by user.
        If target_date is provided (YYYY-MM-DD) the method returns counts for that day only.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            if target_date:
                query = """
                    SELECT u.user_id, u.name, COUNT(ar.record_id) as attendance_count
                    FROM users u
                    LEFT JOIN attendance_records ar ON u.user_id = ar.user_id
                    WHERE DATE(ar.timestamp) = ?
                    GROUP BY u.user_id, u.name
                    ORDER BY attendance_count DESC;
                """
                cur.execute(query, (target_date,))
            else:
                query = """
                    SELECT u.user_id, u.name, COUNT(ar.record_id) as attendance_count
                    FROM users u
                    LEFT JOIN attendance_records ar ON u.user_id = ar.user_id
                    GROUP BY u.user_id, u.name
                    ORDER BY attendance_count DESC;
                """
                cur.execute(query)
            rows = cur.fetchall()
            cur.close()
            return [(r["user_id"], r["name"], r["attendance_count"]) for r in rows]

    def get_attendance_for_date(self, target_date: str) -> List[Dict[str, Any]]:
        """
        Returns attendance rows for a given date YYYY-MM-DD:
         [{'record_id':..., 'user_id':..., 'name':..., 'timestamp':...}, ...]
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ar.record_id, ar.user_id, u.name, ar.timestamp
                FROM attendance_records ar
                JOIN users u ON ar.user_id = u.user_id
                WHERE DATE(ar.timestamp) = ?
                ORDER BY ar.timestamp ASC;
                """,
                (target_date,)
            )
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]

    # ---------------------------
    # Utility
    # ---------------------------
    def close(self):
        # Nothing to do because we open per-method connections, but keep for API compatibility
        logger.info("FaceDatabase.close() called (no-op for per-call connections).")
