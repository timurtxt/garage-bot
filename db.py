import sqlite3
from datetime import datetime
from typing import Optional, Set

DB_PATH = "garage_bot.db"


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS garage_state (
                    unit_id    INTEGER PRIMARY KEY,
                    unit_name  TEXT,
                    entered_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    unit_id    INTEGER NOT NULL,
                    unit_name  TEXT,
                    event_type TEXT NOT NULL,
                    ts         TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_unit
                    ON events(unit_id, event_type, ts);
            """)

    def get_garage_state(self) -> Set[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT unit_id FROM garage_state").fetchall()
        return {r["unit_id"] for r in rows}

    def save_garage_state(self, unit_ids: Set[int]):
        with self._connect() as conn:
            conn.execute("DELETE FROM garage_state")
            conn.executemany(
                "INSERT INTO garage_state(unit_id) VALUES(?)",
                [(uid,) for uid in unit_ids],
            )

    def record_entry(self, unit_id: int, unit_name: str):
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO garage_state(unit_id, unit_name, entered_at)
                VALUES(?,?,?)
                ON CONFLICT(unit_id) DO UPDATE
                    SET unit_name=excluded.unit_name, entered_at=excluded.entered_at
                """,
                (unit_id, unit_name, now),
            )
            conn.execute(
                "INSERT INTO events(unit_id,unit_name,event_type,ts) VALUES(?,?,'enter',?)",
                (unit_id, unit_name, now),
            )

    def record_exit(self, unit_id: int, unit_name: str):
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM garage_state WHERE unit_id=?", (unit_id,))
            conn.execute(
                "INSERT INTO events(unit_id,unit_name,event_type,ts) VALUES(?,?,'exit',?)",
                (unit_id, unit_name, now),
            )

    def get_last_exit(self, unit_id: int) -> Optional[datetime]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT ts FROM events
                WHERE unit_id=? AND event_type='exit'
                ORDER BY ts DESC LIMIT 1
                """,
                (unit_id,),
            ).fetchone()
        if row:
            try:
                return datetime.fromisoformat(row["ts"])
            except Exception:
                return None
        return None
