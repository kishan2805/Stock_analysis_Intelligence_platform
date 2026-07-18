"""Small, local, versioned cache. Audio is deliberately never persisted."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path


class SignalCache:
    def __init__(self, path: str = ".cache/youtube_signals.sqlite3"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self.path)

    @staticmethod
    def key(namespace: str, *parts: str) -> str:
        return f"{namespace}:" + hashlib.sha256("|".join(parts).encode()).hexdigest()

    def get(self, key: str):
        with self._connect() as db:
            row = db.execute("SELECT value FROM records WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO records(key, value) VALUES (?, ?)", (key, json.dumps(value)))
