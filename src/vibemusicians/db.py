"""Lightweight SQLite storage for the artist roster and generated tracks.

No ORM — this app has two small tables and doesn't need one.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_id INTEGER REFERENCES artists(id),
    title TEXT NOT NULL,
    lyrics TEXT,
    style_prompt TEXT NOT NULL,
    negative_tags TEXT,
    instrumental INTEGER NOT NULL DEFAULT 0,
    creative_rationale TEXT,
    trend_brief TEXT,
    suno_task_id TEXT,
    audio_path TEXT,
    cover_art_path TEXT,
    soundcloud_track_id TEXT,
    soundcloud_url TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _migrate_legacy_persona(conn: sqlite3.Connection) -> None:
    """One-time upgrade from the old single-persona schema to the artist roster.

    Older DBs have a `persona` table (one row, id=1) and a `tracks` table with
    no `artist_id` column. Preserve that data by turning it into artist #1 and
    backfilling artist_id on its tracks, rather than losing it.
    """
    if not _column_exists(conn, "tracks", "artist_id"):
        conn.execute("ALTER TABLE tracks ADD COLUMN artist_id INTEGER REFERENCES artists(id)")
    if not _column_exists(conn, "tracks", "cover_art_path"):
        conn.execute("ALTER TABLE tracks ADD COLUMN cover_art_path TEXT")
    if not _column_exists(conn, "tracks", "creative_rationale"):
        conn.execute("ALTER TABLE tracks ADD COLUMN creative_rationale TEXT")

    has_legacy_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'persona'"
    ).fetchone()
    if not has_legacy_table:
        return

    legacy_row = conn.execute("SELECT data FROM persona WHERE id = 1").fetchone()
    if legacy_row:
        already_migrated = conn.execute("SELECT COUNT(*) AS n FROM artists").fetchone()["n"]
        if not already_migrated:
            persona = json.loads(legacy_row["data"])
            cur = conn.execute(
                "INSERT INTO artists (name, data) VALUES (?, ?)",
                (persona["name"], json.dumps(persona)),
            )
            conn.execute(
                "UPDATE tracks SET artist_id = ? WHERE artist_id IS NULL", (cur.lastrowid,)
            )
    conn.execute("DROP TABLE persona")


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        _migrate_legacy_persona(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_artist(db_path: Path, persona: dict[str, Any]) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO artists (name, data) VALUES (?, ?)",
            (persona["name"], json.dumps(persona)),
        )
        return int(cur.lastrowid)


def _artist_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = json.loads(row["data"])
    data["id"] = row["id"]
    data["created_at"] = row["created_at"]
    return data


def get_artist(db_path: Path, artist_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        return _artist_row_to_dict(row) if row else None


def get_artist_by_name(db_path: Path, name: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM artists WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        return _artist_row_to_dict(row) if row else None


def list_artists(db_path: Path) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM artists ORDER BY id").fetchall()
        return [_artist_row_to_dict(row) for row in rows]


@dataclass
class Track:
    artist_id: int
    title: str
    style_prompt: str
    lyrics: str | None = None
    negative_tags: str | None = None
    instrumental: bool = False
    creative_rationale: str | None = None
    trend_brief: str | None = None
    suno_task_id: str | None = None
    audio_path: str | None = None
    cover_art_path: str | None = None
    soundcloud_track_id: str | None = None
    soundcloud_url: str | None = None
    status: str = "created"
    id: int | None = field(default=None)


def create_track(db_path: Path, track: Track) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO tracks
                (artist_id, title, lyrics, style_prompt, negative_tags, instrumental,
                 creative_rationale, trend_brief, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track.artist_id,
                track.title,
                track.lyrics,
                track.style_prompt,
                track.negative_tags,
                int(track.instrumental),
                track.creative_rationale,
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


def list_tracks(db_path: Path, artist_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        if artist_id is not None:
            rows = conn.execute(
                "SELECT t.*, a.name AS artist_name FROM tracks t "
                "LEFT JOIN artists a ON a.id = t.artist_id "
                "WHERE t.artist_id = ? ORDER BY t.id DESC LIMIT ?",
                (artist_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.*, a.name AS artist_name FROM tracks t "
                "LEFT JOIN artists a ON a.id = t.artist_id "
                "ORDER BY t.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def count_recent_publishes(db_path: Path, artist_id: int, days: int = 7) -> int:
    """Tracks published by this artist within the last `days` days.

    `updated_at` doubles as the publish timestamp here: it's only set to a
    fresh value the moment `status` transitions to 'published', and status
    never changes after that, so it doesn't drift on later, unrelated edits.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM tracks "
            "WHERE artist_id = ? AND status = 'published' AND updated_at >= datetime('now', ?)",
            (artist_id, f"-{days} days"),
        ).fetchone()
        return int(row["n"])
