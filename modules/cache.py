"""Small SQLite cache stored next to config.yml.

Holds MusicBrainz lookups, ISRCs read from files and per-user sync state, so
repeated runs are cheap and polite to the MusicBrainz API.
"""
import json
import sqlite3
import time


class Cache:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                ns TEXT NOT NULL, k TEXT NOT NULL, v TEXT NOT NULL, ts REAL NOT NULL,
                PRIMARY KEY (ns, k)
            );
            CREATE TABLE IF NOT EXISTS file_isrc (
                path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, isrcs TEXT NOT NULL
            );
            """
        )
        self.db.commit()

    def get(self, ns: str, key: str, max_age: float | None = None):
        row = self.db.execute("SELECT v, ts FROM kv WHERE ns=? AND k=?", (ns, key)).fetchone()
        if row is None:
            return None
        if max_age is not None and time.time() - row[1] > max_age:
            return None
        return json.loads(row[0])

    def put(self, ns: str, key: str, value) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO kv (ns, k, v, ts) VALUES (?, ?, ?, ?)",
            (ns, key, json.dumps(value), time.time()),
        )
        self.db.commit()

    def get_file_isrcs(self, path: str, mtime: float, size: int):
        row = self.db.execute("SELECT mtime, size, isrcs FROM file_isrc WHERE path=?", (path,)).fetchone()
        if row and row[0] == mtime and row[1] == size:
            return set(json.loads(row[2]))
        return None

    def put_file_isrcs(self, path: str, mtime: float, size: int, isrcs) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO file_isrc (path, mtime, size, isrcs) VALUES (?, ?, ?, ?)",
            (path, mtime, size, json.dumps(sorted(isrcs))),
        )
        self.db.commit()
