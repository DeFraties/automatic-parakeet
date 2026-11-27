"""Small on-disk SQLite caches for ingestion: HTTP responses (pages only) and robots.txt.

Geocoding keys are SHA-256 hashes of the query, so street addresses are never written to disk.
"""

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


def hash_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class SqliteCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (ns TEXT, key TEXT, value TEXT, stored_at REAL,"
            " PRIMARY KEY (ns, key))"
        )
        self._conn.commit()

    def get(self, ns: str, key: str, max_age_s: float | None = None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value, stored_at FROM kv WHERE ns=? AND key=?", (ns, key)
            ).fetchone()
        if row is None:
            return None
        value, stored_at = row
        if max_age_s is not None and time.time() - stored_at > max_age_s:
            return None
        return json.loads(value)

    def set(self, ns: str, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (ns, key, value, stored_at) VALUES (?, ?, ?, ?)",
                (ns, key, json.dumps(value), time.time()),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
