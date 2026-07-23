import os
import sqlite3
import threading
import time


class ShutdownStateStore:
    """Small cross-worker state store for chat shutdown flags.

    SQLite is used because Gunicorn workers do not share Python memory.
    The state is intentionally runtime-local; a deploy/restart wakes the bot.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get(
            "SHUTDOWN_STATE_DB",
            "/tmp/ai_hashimoto_shutdown_state.sqlite3",
        )
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _initialize(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shutdown_state (
                    chat_id TEXT PRIMARY KEY,
                    is_shutdown INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def set(self, chat_id: str, value: bool):
        if not chat_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO shutdown_state(chat_id, is_shutdown, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    is_shutdown = excluded.is_shutdown,
                    updated_at = excluded.updated_at
                """,
                (chat_id, 1 if value else 0, time.time()),
            )
            conn.commit()

    def get(self, chat_id: str) -> bool:
        if not chat_id:
            return False
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT is_shutdown FROM shutdown_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return bool(row and row[0])
