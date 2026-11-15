import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT,
    workdir TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    youtube_id TEXT,
    publish_at TEXT,
    duration_s REAL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    avg_view_pct REAL,
    avg_view_s REAL,
    subs_gained INTEGER,
    stats_updated_at TEXT
);
CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    video_id TEXT,
    author TEXT,
    text TEXT,
    action TEXT,
    reply TEXT,
    handled_at TEXT
);
CREATE TABLE IF NOT EXISTS log (
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    data TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def log(self, event: str, **data) -> None:
        self.conn.execute("INSERT INTO log VALUES (?,?,?)", (now(), event, json.dumps(data, ensure_ascii=False)))
        self.conn.commit()

    def add_video(self, topic: str, workdir: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO videos (created_at, topic, workdir) VALUES (?,?,?)", (now(), topic, workdir)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_video(self, vid: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE videos SET {cols} WHERE id=?", (*fields.values(), vid))
        self.conn.commit()

    def update_by_youtube_id(self, yt_id: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE videos SET {cols} WHERE youtube_id=?", (*fields.values(), yt_id))
        self.conn.commit()

    def videos(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.conn.execute("SELECT * FROM videos WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        return self.conn.execute("SELECT * FROM videos ORDER BY id DESC").fetchall()

    def past_topics(self, limit: int = 100) -> list[str]:
        rows = self.conn.execute("SELECT topic, title FROM videos ORDER BY id DESC LIMIT ?", (limit,))
        return [f"{r['topic']} | {r['title'] or ''}" for r in rows]

    def comment_handled(self, comment_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM comments WHERE comment_id=?", (comment_id,)).fetchone() is not None

    def save_comment(self, comment_id, video_id, author, text, action, reply) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO comments VALUES (?,?,?,?,?,?,?)",
            (comment_id, video_id, author, text, action, reply, now()),
        )
        self.conn.commit()
