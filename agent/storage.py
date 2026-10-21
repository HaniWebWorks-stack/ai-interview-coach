"""
Saved interview history (SQLite file on this laptop only, outside OneDrive):
  %LOCALAPPDATA%\\ai-interview-coach\\coach.db

Nothing is saved unless the user ticked "Save my reports" for that session.
No audio recordings are ever stored. Users can delete one or all sessions.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sqlite3
import time

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
DB_PATH = APP_DATA / "coach.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    interview_type TEXT,
    role TEXT,
    experience_level TEXT,
    category TEXT,
    minutes REAL,
    end_reason TEXT,
    overall_score INTEGER,
    report_json TEXT,
    transcript_json TEXT
);
-- Added 2026-10-14 (Preparation Studio). New tables only: existing data is untouched.
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    kind TEXT NOT NULL,          -- insights | diagram | studypack | resume_match
    title TEXT,
    source_json TEXT,            -- what it was made from (report ids, topic, ...)
    data_json TEXT
);
CREATE INDEX IF NOT EXISTS materials_kind ON materials(kind, created_at);
CREATE TABLE IF NOT EXISTS progress_items (
    key TEXT PRIMARY KEY,        -- e.g. roadmap:<material id>:<node id>
    status TEXT NOT NULL,        -- pending | in_progress | done
    updated_at REAL NOT NULL
);
"""


@contextlib.contextmanager
def connect(path: pathlib.Path = DB_PATH):
    """Open the database, create any missing tables, commit, and always close."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_session(session_id: str, profile: dict, category: str, minutes: float, end_reason: str,
                 report: dict, transcript: list[dict], path: pathlib.Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id, time.time(), profile.get("interview_type"), profile.get("role"),
                profile.get("experience_level"), category, round(minutes, 1), end_reason,
                report.get("overall_score"), json.dumps(report, ensure_ascii=False),
                json.dumps(transcript, ensure_ascii=False),
            ),
        )


def list_sessions(path: pathlib.Path = DB_PATH) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, interview_type, role, experience_level, category, minutes, "
            "end_reason, overall_score FROM sessions ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str, path: pathlib.Path = DB_PATH) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["report"] = json.loads(data.pop("report_json") or "{}")
    data["transcript"] = json.loads(data.pop("transcript_json") or "[]")
    return data


def update_report(session_id: str, report: dict, path: pathlib.Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE sessions SET report_json = ? WHERE id = ?",
                     (json.dumps(report, ensure_ascii=False), session_id))


def delete_session(session_id: str, path: pathlib.Path = DB_PATH) -> bool:
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return cur.rowcount > 0


def delete_all(path: pathlib.Path = DB_PATH) -> int:
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM sessions")
    return cur.rowcount


# --- Preparation Studio materials and progress ------------------------------

def save_material(material_id: str, kind: str, title: str, source: dict, data: dict,
                  path: pathlib.Path = DB_PATH) -> dict:
    now = time.time()
    with connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO materials VALUES (?,?,?,?,?,?,?)",
            (material_id, now, now, kind, title[:200], json.dumps(source, ensure_ascii=False),
             json.dumps(data, ensure_ascii=False)),
        )
    return get_material(material_id, path)


def _material_row(row) -> dict:
    d = dict(row)
    d["source"] = json.loads(d.pop("source_json") or "{}")
    d["data"] = json.loads(d.pop("data_json") or "{}")
    return d


def get_material(material_id: str, path: pathlib.Path = DB_PATH) -> dict | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    return _material_row(row) if row else None


def list_materials(kind: str | None = None, path: pathlib.Path = DB_PATH, with_data: bool = False) -> list[dict]:
    cols = "*" if with_data else "id, created_at, updated_at, kind, title, source_json, '{}' AS data_json"
    with connect(path) as conn:
        if kind:
            rows = conn.execute(f"SELECT {cols} FROM materials WHERE kind = ? ORDER BY created_at DESC", (kind,)).fetchall()
        else:
            rows = conn.execute(f"SELECT {cols} FROM materials ORDER BY created_at DESC").fetchall()
    return [_material_row(r) for r in rows]


def update_material_data(material_id: str, data: dict, path: pathlib.Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE materials SET data_json = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), time.time(), material_id))


def delete_material(material_id: str, path: pathlib.Path = DB_PATH) -> bool:
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        conn.execute("DELETE FROM progress_items WHERE key LIKE ?", (f"%:{material_id}:%",))
    return cur.rowcount > 0


PROGRESS_STATES = ("pending", "in_progress", "done")


def set_progress(key: str, status: str, path: pathlib.Path = DB_PATH) -> None:
    if status not in PROGRESS_STATES:
        raise ValueError(f"status must be one of {PROGRESS_STATES}")
    with connect(path) as conn:
        conn.execute("INSERT OR REPLACE INTO progress_items VALUES (?,?,?)", (key[:300], status, time.time()))


def get_progress(prefix: str, path: pathlib.Path = DB_PATH) -> dict[str, dict]:
    with connect(path) as conn:
        rows = conn.execute("SELECT * FROM progress_items WHERE key LIKE ?", (prefix + "%",)).fetchall()
    return {r["key"]: {"status": r["status"], "updated_at": r["updated_at"]} for r in rows}


def list_full_sessions(limit: int = 50, path: pathlib.Path = DB_PATH) -> list[dict]:
    """Newest first, with reports (for progress analytics and the studio)."""
    out = []
    for item in list_sessions(path)[:limit]:
        full = get_session(item["id"], path)
        if full:
            out.append(full)
    return out
