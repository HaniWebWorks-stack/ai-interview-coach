"""
HTTP API for the Preparation Studio, Progress, Resume match and the learning
assistant. Registered by viewer_server.make_app(). Runs only on this laptop
(127.0.0.1); the Google key stays here and is never sent to the browser.
"""

from __future__ import annotations

import os
import secrets
import time

from aiohttp import web

import progress as prog
import resume as rs
import storage
import studio

KEY = lambda: os.getenv("GOOGLE_API_KEY", "")  # noqa: E731
_busy: set[str] = set()  # stops duplicate submissions of the same expensive job


def _err(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


class _Once:
    """`async with _Once("insights")` -> 409 if the same job is already running."""

    def __init__(self, key: str):
        self.key = key

    async def __aenter__(self):
        if self.key in _busy:
            raise web.HTTPConflict(text='{"error": "This is already being created. Please wait."}',
                                   content_type="application/json")
        _busy.add(self.key)

    async def __aexit__(self, *exc):
        _busy.discard(self.key)


def _studio_error(e: Exception) -> web.Response:
    if isinstance(e, studio.StudioError):
        return _err(str(e), 502)
    return _err(studio.friendly_error(e), 502)


# --- targeted practice (validated before it reaches the coach) ----------------

def clean_focus(raw) -> dict | None:
    if not isinstance(raw, dict) or not str(raw.get("topic", "")).strip():
        return None
    s = studio._s
    return {
        "topic": s(raw.get("topic"), 120),
        "kind": raw.get("kind") if raw.get("kind") in ("weakness", "recommendation", "reassess", "resume", "studio") else "studio",
        "questions": studio._list(raw.get("questions"), 5, 300),
        "notes": s(raw.get("notes"), 600),
        "interview_type": s(raw.get("interview_type"), 80),
        "role": s(raw.get("role"), 80),
        "level": s(raw.get("level"), 60),
    }


# --- progress ------------------------------------------------------------------

async def progress_overview(request: web.Request) -> web.Response:
    sessions = storage.list_full_sessions(limit=200)
    data = prog.analyse(sessions, category=request.query.get("category", ""), role=request.query.get("role", ""))
    return web.json_response(data)


# --- insights (preparation engine) --------------------------------------------

def _scored_or_practice(limit: int = 10) -> list[dict]:
    return [s for s in storage.list_full_sessions(limit=limit) if (s.get("report") or {}).get("criteria")
            or (s.get("report") or {}).get("kind") == "practice"]


async def get_insights(_: web.Request) -> web.Response:
    items = storage.list_materials("insights", with_data=True)
    sessions = _scored_or_practice()
    current_ids = [s["id"] for s in sessions]
    latest = items[0] if items else None
    stale = bool(latest) and latest["source"].get("session_ids") != current_ids
    return web.json_response({"insights": latest, "stale": stale, "session_count": len(sessions)})


async def make_insights(request: web.Request) -> web.Response:
    sessions = _scored_or_practice()
    if not sessions:
        return _err("There are no saved sessions yet. Tick 'Save my interview report' before a session, "
                    "then come back here.", 404)
    ids = [s["id"] for s in sessions]
    previous_items = storage.list_materials("insights", with_data=True)
    if previous_items and previous_items[0]["source"].get("session_ids") == ids and not (await _json(request)).get("force"):
        return web.json_response({"insights": previous_items[0], "cached": True})
    previous = (previous_items[0]["data"].get("weaknesses") if previous_items else []) or []
    async with _Once("insights"):
        try:
            data = await studio.make_insights(KEY(), sessions, previous)
        except Exception as e:
            return _studio_error(e)
    mid = "ins-" + secrets.token_hex(6)
    item = storage.save_material(mid, "insights", "Preparation insights", {"session_ids": ids}, data)
    return web.json_response({"insights": item, "cached": False})


# --- diagrams and study packs ----------------------------------------------------

def _context_for(source: dict) -> str:
    """Personal context for a generator: one report, the latest insights, or a resume match."""
    kind, sid = (source or {}).get("type"), str((source or {}).get("id", ""))[:64]
    if kind == "report" and sid:
        s = storage.get_session(sid)
        return studio.report_context(s) if s else ""
    if kind == "insights":
        items = storage.list_materials("insights", with_data=True)
        if items:
            d = items[0]["data"]
            return (d.get("summary", "") + "\nWeaknesses: " + "; ".join(
                f"{w['topic']} ({w['kind']}): {w['evidence']}" for w in d.get("weaknesses", [])) +
                "\nStrengths: " + "; ".join(f"{x['topic']}: {x['evidence']}" for x in d.get("strengths", [])))[:6000]
    if kind == "material" and sid:
        m = storage.get_material(sid)
        return studio.material_context(m) if m else ""
    if kind == "all":
        return studio.digest_reports(_scored_or_practice(), max_chars=8000)
    return ""


async def make_diagram(request: web.Request) -> web.Response:
    body = await _json(request)
    kind, topic = body.get("kind"), str(body.get("topic", "")).strip()
    if kind not in studio.DIAGRAM_KINDS:
        return _err("Choose a diagram type.")
    if not topic:
        return _err("Enter a topic for the diagram.")
    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    if kind == "skillgap" and source.get("type") not in ("report", "insights", "all"):
        source = {"type": "all"}  # a skill-gap diagram must be based on real evidence
    async with _Once(f"diagram:{kind}:{topic.lower()}"):
        try:
            data = await studio.make_diagram(KEY(), kind, topic, _context_for(source))
        except Exception as e:
            return _studio_error(e)
    mid = "dia-" + secrets.token_hex(6)
    item = storage.save_material(mid, "diagram", data["title"], {"kind": kind, "topic": topic, "source": source}, data)
    return web.json_response({"material": item})


async def make_studypack(request: web.Request) -> web.Response:
    body = await _json(request)
    topic = str(body.get("topic", "")).strip()
    if not topic:
        return _err("Enter a topic for the study pack.")
    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    async with _Once(f"pack:{topic.lower()}"):
        try:
            data = await studio.make_studypack(KEY(), topic, _context_for(source))
        except Exception as e:
            return _studio_error(e)
    mid = "pack-" + secrets.token_hex(6)
    item = storage.save_material(mid, "studypack", data["title"], {"topic": topic, "source": source}, data)
    return web.json_response({"material": item})


async def list_materials(request: web.Request) -> web.Response:
    kind = request.query.get("kind") or None
    if kind and kind not in ("insights", "diagram", "studypack", "resume_match"):
        return _err("unknown kind")
    return web.json_response({"materials": storage.list_materials(kind)})


async def get_material(request: web.Request) -> web.Response:
    m = storage.get_material(request.match_info["mid"])
    if not m:
        return _err("not found", 404)
    if m["kind"] == "diagram" and m["data"].get("kind") == "roadmap":
        states = storage.get_progress(f"roadmap:{m['id']}:")
        for n in m["data"]["nodes"]:
            n["status"] = states.get(f"roadmap:{m['id']}:{n['id']}", {}).get("status", "pending")
    return web.json_response({"material": m})


async def edit_material(request: web.Request) -> web.Response:
    """Edit a diagram node's label or add a personal note."""
    m = storage.get_material(request.match_info["mid"])
    if not m or m["kind"] != "diagram":
        return _err("not found", 404)
    body = await _json(request)
    node = next((n for n in m["data"]["nodes"] if n["id"] == body.get("node_id")), None)
    if not node:
        return _err("That part of the diagram no longer exists.", 404)
    if "label" in body:
        label = studio._s(body["label"], 70)
        if not label:
            return _err("The label cannot be empty.")
        node["label"] = label
    if "note" in body:
        node["note"] = studio._s(body["note"], 1000)
    storage.update_material_data(m["id"], m["data"])
    return web.json_response({"node": node})


async def delete_material(request: web.Request) -> web.Response:
    return web.json_response({"deleted": storage.delete_material(request.match_info["mid"])})


async def set_progress_item(request: web.Request) -> web.Response:
    body = await _json(request)
    key, status = str(body.get("key", "")), body.get("status")
    if not key.startswith("roadmap:") or status not in storage.PROGRESS_STATES:
        return _err("invalid progress item")
    storage.set_progress(key, status)
    return web.json_response({"key": key, "status": status})


# --- resume match ----------------------------------------------------------------

async def resume_extract(request: web.Request) -> web.Response:
    if (request.content_length or 0) > rs.MAX_UPLOAD_BYTES + 100_000:
        return _err("The file is larger than 5 MB.", 413)
    try:
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            return _err("No file was sent.")
        data = await field.read(decode=False)
        text = rs.extract_text(field.filename or "", bytes(data))
    except rs.ResumeError as e:
        return _err(str(e))
    except Exception:
        return _err("The file could not be read.")
    if len(text) < rs.MIN_TEXT_CHARS:
        return _err("Very little text was found in this file. If it is a scanned image, paste the text instead.")
    return web.json_response({"text": text, "chars": len(text)})


async def resume_match(request: web.Request) -> web.Response:
    body = await _json(request)
    try:
        resume_text, job = rs.validate_inputs(str(body.get("resume_text", "")), str(body.get("job_description", "")))
    except rs.ResumeError as e:
        return _err(str(e))
    async with _Once("resume"):
        try:
            data = await studio.make_resume_match(KEY(), resume_text, job)
        except Exception as e:
            return _studio_error(e)
    if body.get("save"):
        mid = "res-" + secrets.token_hex(6)
        # Only the analysis is stored (not the resume text).
        item = storage.save_material(mid, "resume_match", data["role_title"],
                                     {"job_excerpt": job[:300], "saved_at": time.time()}, data)
        return web.json_response({"material": item, "saved": True})
    return web.json_response({"material": {"id": "", "kind": "resume_match", "title": data["role_title"],
                                           "data": data, "source": {}, "created_at": time.time()},
                              "saved": False})


# --- learning assistant ------------------------------------------------------------

async def ask_assistant(request: web.Request) -> web.Response:
    body = await _json(request)
    messages = [m for m in (body.get("messages") or []) if isinstance(m, dict) and str(m.get("text", "")).strip()]
    if not messages or messages[-1].get("role") != "user":
        return _err("Type a question first.")
    ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
    context = ""
    if ctx.get("type") == "report":
        context = _context_for({"type": "report", "id": ctx.get("id")})
    elif ctx.get("type") == "material":
        m = storage.get_material(str(ctx.get("id", ""))[:64])
        context = studio.material_context(m, str(ctx.get("node_id", ""))) if m else ""
    elif ctx.get("type") == "insights":
        context = _context_for({"type": "insights"})
    try:
        data = await studio.assistant(KEY(), context, messages)
    except Exception as e:
        return _studio_error(e)
    return web.json_response(data)


def register(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/progress", progress_overview)
    r.add_get("/api/insights", get_insights)
    r.add_post("/api/insights", make_insights)
    r.add_post("/api/diagrams", make_diagram)
    r.add_post("/api/studypacks", make_studypack)
    r.add_get("/api/materials", list_materials)
    r.add_get("/api/materials/{mid}", get_material)
    r.add_patch("/api/materials/{mid}", edit_material)
    r.add_delete("/api/materials/{mid}", delete_material)
    r.add_post("/api/progress-items", set_progress_item)
    r.add_post("/api/resume/extract", resume_extract)
    r.add_post("/api/resume/match", resume_match)
    r.add_post("/api/assistant", ask_assistant)
