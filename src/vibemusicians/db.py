"""Lightweight SQLite storage for the persona and generated tracks.

No ORM — this app has two small tables and doesn't need one.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS persona (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    lyrics TEXT,
    style_prompt TEXT NOT NULL,
    negative_tags TEXT,
    instrumental INTEGER NOT NULL DEFAULT 0,
    trend_brief TEXT,
    suno_task_id TEXT,
    audio_path TEXT,
    soundcloud_track_id TEXT,
    soundcloud_url TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def load_persona(db_path: Path) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT data FROM persona WHERE id = 1").fetchone()
        return json.loads(row["data"]) if row else None


def save_persona(db_path: Path, persona: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO persona (id, data, updated_at) VALUES (1, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
            """,
            (json.dumps(persona),),
        )


@dataclass
class Track:
    title: str
    style_prompt: str
    lyrics: str | None = None
    negative_tags: str | None = None
    instrumental: bool = False
    trend_brief: str | None = None
    suno_task_id: str | None = None
    audio_path: str | None = None
    soundcloud_track_id: str | None = None
    soundcloud_url: str | None = None
    status: str = "created"
    id: int | None = field(default=None)


def create_track(db_path: Path, track: Track) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO tracks (title, lyrics, style_prompt, negative_tags, instrumental, trend_brief, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track.title,
                track.lyrics,
                track.style_prompt,
                track.negative_tags,
                int(track.instrumental),
                track.trend_brief,
                track.status,
            ),
        )
        return int(cur.lastrowid)


def update_track(db_path: Path, track_id: int, **fields: Any) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key} = ?" for key in fields)
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE tracks SET {columns}, updated_at = datetime('now') WHERE id = ?",
            (*fields.values(), track_id),
        )


def get_track(db_path: Path, track_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        return dict(row) if row else None


def list_tracks(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tracks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
