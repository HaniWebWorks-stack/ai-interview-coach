"""
Local web server for the AI Interview Coach app (runs only on this laptop,
http://localhost:8765). It never sends a secret key to the browser.

API used by the app:
- POST   /api/token          short-lived room ticket (10 min) + the user's consent
                             choices. Starting a session closes any older one.
- GET    /api/settings       current settings      POST /api/settings  save them
- GET    /api/avatars        LiveAvatar's public avatars (fetched with the key here)
- GET    /api/status         avatar credits left
- GET    /api/history        saved reports         DELETE /api/history       delete all
- GET    /api/history/{id}   one saved report      DELETE /api/history/{id}  delete one
- GET    /api/questions      every question asked in saved sessions (with answers)
- GET    /api/worksheet/{id} one session as a worksheet (model answers written on first open)
"""

import asyncio
import datetime
import json
import mimetypes
import os
import pathlib
import secrets
import webbrowser

import aiohttp
from aiohttp import web
from dotenv import dotenv_values, load_dotenv, set_key
from livekit import api

import coach_logic
import evaluation
import storage
import studio_api

# Windows sometimes maps these to the wrong type, which stops the browser from
# running the 3D avatar's code, so set them explicitly.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("application/octet-stream", ".bin")

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
load_dotenv(APP_DATA / "agent.env")

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "viewer" / "app"          # the built React app
SETTINGS_FILE = ROOT / "agent" / "settings.env"
HOST, PORT = "127.0.0.1", 8765
AGENT_NAME = "interview-coach"
LIVEAVATAR_API = "https://api.liveavatar.com/v1"
WAYNE_SANDBOX_AVATAR = "dd73ea75-1218-4ef3-92ce-606d5f7fbc0a"

VOICES = {"Kore": "female", "Aoede": "female", "Leda": "female",
          "Charon": "male", "Puck": "male", "Orus": "male"}
LANGUAGES = ["English", "Urdu", "Urdu and English"]
SPEEDS = {"fast": 500, "balanced": 700, "patient": 1000}  # ms of silence before the coach replies
QUALITIES = ["low", "medium", "high"]
AVATAR_MODES = ["3d", "video"]  # 3d = free in-browser avatar, video = LiveAvatar


def livekit_api() -> api.LiveKitAPI:
    return api.LiveKitAPI(url=os.getenv("LIVEKIT_URL"), api_key=os.getenv("LIVEKIT_API_KEY"),
                          api_secret=os.getenv("LIVEKIT_API_SECRET"))


async def liveavatar_get(path: str) -> dict:
    headers = {"X-API-KEY": os.getenv("LIVEAVATAR_API_KEY", ""), "accept": "application/json"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.get(LIVEAVATAR_API + path, headers=headers) as r:
            if r.status != 200:
                raise web.HTTPBadGateway(text=f"LiveAvatar answered HTTP {r.status}")
            return await r.json()


def read_settings() -> dict:
    s = dotenv_values(SETTINGS_FILE)
    silence = int(s.get("TURN_SILENCE_MS", "500") or 500)
    speed = min(SPEEDS, key=lambda k: abs(SPEEDS[k] - silence))
    avatar_id = s.get("LIVEAVATAR_AVATAR_ID", WAYNE_SANDBOX_AVATAR)
    return {
        "avatar_mode": s.get("AVATAR_MODE", "3d") if s.get("AVATAR_MODE", "3d") in AVATAR_MODES else "3d",
        "language": s.get("COACH_LANGUAGE", "English"),
        "voice": s.get("GEMINI_VOICE", "Kore"),
        "avatar_id": avatar_id,
        "avatar_name": s.get("LIVEAVATAR_AVATAR_NAME", "Wayne"),
        "avatar_sandbox": avatar_id == WAYNE_SANDBOX_AVATAR,
        "speed": speed,
        "video_quality": s.get("LIVEAVATAR_VIDEO_QUALITY", "medium"),
        "save_history_default": (s.get("SAVE_HISTORY_DEFAULT", "false") or "false").lower() == "true",
        "options": {"voices": VOICES, "languages": LANGUAGES, "speeds": list(SPEEDS), "qualities": QUALITIES},
    }


# --- pages -------------------------------------------------------------------

async def index(_: web.Request) -> web.StreamResponse:
    page = APP_DIR / "index.html"
    if not page.exists():
        return web.Response(text="The app files are missing (viewer/app). Build them with: cd frontend, npm install, npm run build.", status=500)
    # Never reuse an old copy of the page: after an update the browser must
    # load the new app (an old cached page showed "Voice mode" instead of the
    # 3D interviewer).
    return web.FileResponse(page, headers={"Cache-Control": "no-store, max-age=0"})


# --- api ---------------------------------------------------------------------

async def token(request: web.Request) -> web.Response:
    url, key, secret = os.getenv("LIVEKIT_URL", ""), os.getenv("LIVEKIT_API_KEY", ""), os.getenv("LIVEKIT_API_SECRET", "")
    if not (url and key and secret):
        return web.json_response({"error": "LiveKit details are not saved on this laptop."}, status=500)
    try:
        body = await request.json()
    except Exception:
        body = {}
    save_history = bool(body.get("save_history", False))
    focus = studio_api.clean_focus(body.get("focus"))  # targeted practice (optional)

    # One session at a time: close every earlier coach room in this project.
    lk = livekit_api()
    try:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        for r in rooms.rooms:
            if r.name.startswith("coach-"):
                await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
                print(f"Closed earlier session room {r.name}")
    except Exception as e:
        print(f"Could not close earlier rooms: {type(e).__name__}: {e}")
    finally:
        await lk.aclose()

    room = f"coach-{secrets.token_hex(4)}"
    identity = f"user-{secrets.token_hex(3)}"
    jwt = (
        api.AccessToken(api_key=key, api_secret=secret)
        .with_identity(identity)
        .with_name("You")
        .with_metadata(json.dumps({"save_history": save_history, **({"focus": focus} if focus else {})}))
        .with_ttl(datetime.timedelta(minutes=10))
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]))
        .to_jwt()
    )
    return web.json_response({"url": url, "token": jwt, "room": room})


async def get_settings(_: web.Request) -> web.Response:
    return web.json_response(read_settings())


async def post_settings(request: web.Request) -> web.Response:
    body = await request.json()
    errors = []
    if "language" in body:
        if body["language"] in LANGUAGES:
            set_key(str(SETTINGS_FILE), "COACH_LANGUAGE", body["language"], quote_mode="always")
        else:
            errors.append("language")
    if "voice" in body:
        if body["voice"] in VOICES:
            set_key(str(SETTINGS_FILE), "GEMINI_VOICE", body["voice"], quote_mode="never")
        else:
            errors.append("voice")
    if "speed" in body:
        if body["speed"] in SPEEDS:
            set_key(str(SETTINGS_FILE), "TURN_SILENCE_MS", str(SPEEDS[body["speed"]]), quote_mode="never")
        else:
            errors.append("speed")
    if "video_quality" in body:
        if body["video_quality"] in QUALITIES:
            set_key(str(SETTINGS_FILE), "LIVEAVATAR_VIDEO_QUALITY", body["video_quality"], quote_mode="never")
        else:
            errors.append("video_quality")
    if "avatar_mode" in body:
        if body["avatar_mode"] in AVATAR_MODES:
            set_key(str(SETTINGS_FILE), "AVATAR_MODE", body["avatar_mode"], quote_mode="never")
        else:
            errors.append("avatar_mode")
    if "save_history_default" in body:
        set_key(str(SETTINGS_FILE), "SAVE_HISTORY_DEFAULT", "true" if body["save_history_default"] else "false",
                quote_mode="never")
    if "avatar_id" in body:
        data = await liveavatar_get("/avatars/public?page=1&page_size=100")
        names = {a["id"]: a.get("name", "") for a in (data.get("data") or {}).get("results") or []}
        if body["avatar_id"] in names:
            set_key(str(SETTINGS_FILE), "LIVEAVATAR_AVATAR_ID", body["avatar_id"], quote_mode="never")
            set_key(str(SETTINGS_FILE), "LIVEAVATAR_AVATAR_NAME", names[body["avatar_id"]][:60], quote_mode="always")
        else:
            errors.append("avatar_id")
    if errors:
        return web.json_response({"error": "invalid: " + ", ".join(errors)}, status=400)
    return web.json_response(read_settings())


async def avatars(_: web.Request) -> web.Response:
    data = await liveavatar_get("/avatars/public?page=1&page_size=100")
    out = [
        {"id": a["id"], "name": a.get("name", ""), "preview_url": a.get("preview_url"),
         "is_1080p": a.get("is_1080p", False), "sandbox": a["id"] == WAYNE_SANDBOX_AVATAR}
        for a in (data.get("data") or {}).get("results") or []
        if a.get("status") == "ACTIVE" and not a.get("is_expired")
    ]
    return web.json_response({"avatars": out})


async def status(_: web.Request) -> web.Response:
    credits = None
    try:
        data = await liveavatar_get("/users/credits")
        credits = (data.get("data") or {}).get("credits_left")
    except Exception:
        pass
    return web.json_response({"credits_left": credits})


async def history_list(_: web.Request) -> web.Response:
    return web.json_response({"sessions": storage.list_sessions(), "stored_at": str(storage.DB_PATH)})


async def history_get(request: web.Request) -> web.Response:
    item = storage.get_session(request.match_info["sid"])
    if not item:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(item)


async def questions(_: web.Request) -> web.Response:
    """Every question from every saved session, newest session first."""
    out = []
    for item in storage.list_sessions():
        full = storage.get_session(item["id"]) or {}
        qs = coach_logic.session_questions(full.get("report") or {}, full.get("transcript") or [])
        if qs:
            out.append({**item, "kind": (full.get("report") or {}).get("kind", "interview"), "questions": qs})
    return web.json_response({"sessions": out})


# Model answers are written in the background: as soon as a session is saved
# (checked every few seconds), and again when a worksheet is opened. The page
# shows the questions at once and fills in the answers when they are ready.
_jobs: dict[str, asyncio.Task] = {}
_job_errors: dict[str, str] = {}


def _needs_sheet(report: dict, questions: list) -> bool:
    sheet = report.get("worksheet")
    return bool(questions) and (not isinstance(sheet, list) or len(sheet) != len(questions))


async def _write_sheet(sid: str) -> None:
    full = storage.get_session(sid) or {}
    report = full.get("report") or {}
    questions = coach_logic.session_questions(report, full.get("transcript") or [])
    if not _needs_sheet(report, questions):
        return
    try:
        sheet = await evaluation.worksheet(os.getenv("GOOGLE_API_KEY", ""), report.get("profile") or full, questions)
        report = (storage.get_session(sid) or {}).get("report") or report
        report["worksheet"] = sheet
        storage.update_report(sid, report)
        _job_errors.pop(sid, None)
        print(f"Worksheet ready for session {sid} ({len(sheet)} questions)")
    except Exception as e:
        _job_errors[sid] = str(e)
        print(f"Worksheet for {sid} failed: {e}")


def ensure_sheet_job(sid: str) -> asyncio.Task:
    task = _jobs.get(sid)
    if task is None or (task.done() and sid in _job_errors):
        _job_errors.pop(sid, None)
        task = asyncio.get_running_loop().create_task(_write_sheet(sid))
        _jobs[sid] = task
    return task


async def prepare_new_sheets(_: web.Application):
    """Background: write model answers for newly saved sessions."""
    async def loop():
        while True:
            try:
                for item in storage.list_sessions()[:20]:
                    full = storage.get_session(item["id"]) or {}
                    report = full.get("report") or {}
                    qs = coach_logic.session_questions(report, full.get("transcript") or [])
                    if _needs_sheet(report, qs) and item["id"] not in _jobs:
                        await ensure_sheet_job(item["id"])
            except Exception as e:
                print(f"(worksheet background check: {type(e).__name__}: {e})")
            await asyncio.sleep(5)
    task = asyncio.get_running_loop().create_task(loop())
    yield
    task.cancel()


async def worksheet(request: web.Request) -> web.Response:
    """One session as a worksheet. Returns at once; "pending" means the model
    answers are still being written (the page asks again shortly)."""
    sid = request.match_info["sid"]
    full = storage.get_session(sid)
    if not full:
        return web.json_response({"error": "not found"}, status=404)
    report = full.get("report") or {}
    questions = coach_logic.session_questions(report, full.get("transcript") or [])
    meta = {k: full.get(k) for k in ("id", "created_at", "interview_type", "role", "experience_level",
                                     "category", "minutes", "end_reason", "overall_score")}
    meta["kind"] = report.get("kind", "interview")
    pending, error = False, ""
    if _needs_sheet(report, questions):
        task = ensure_sheet_job(sid)
        if task.done():
            error = _job_errors.get(sid, "")
        else:
            pending = True
    sheet = report.get("worksheet") if not _needs_sheet(report, questions) else None
    items = [{**q, **(sheet[i] if sheet else {})} for i, q in enumerate(questions)]
    return web.json_response({"session": meta, "items": items, "pending": pending, "error": error})


async def history_delete(request: web.Request) -> web.Response:
    return web.json_response({"deleted": storage.delete_session(request.match_info["sid"])})


async def history_delete_all(_: web.Request) -> web.Response:
    return web.json_response({"deleted": storage.delete_all()})


ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


@web.middleware
async def local_only(request: web.Request, handler):
    """Only this app, opened on this laptop, may use the API: blocks other
    websites from calling it through the browser (DNS rebinding / cross-site
    requests)."""
    if request.host not in ALLOWED_HOSTS:
        return web.json_response({"error": "forbidden host"}, status=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] not in ALLOWED_HOSTS:
            return web.json_response({"error": "forbidden origin"}, status=403)
    return await handler(request)


def make_app() -> web.Application:
    app = web.Application(middlewares=[local_only], client_max_size=6 * 1024 * 1024)
    app.cleanup_ctx.append(prepare_new_sheets)
    app.router.add_get("/", index)
    app.router.add_post("/api/token", token)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", post_settings)
    app.router.add_get("/api/avatars", avatars)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/history", history_list)
    app.router.add_delete("/api/history", history_delete_all)
    app.router.add_get("/api/history/{sid}", history_get)
    app.router.add_get("/api/questions", questions)
    app.router.add_get("/api/worksheet/{sid}", worksheet)
    app.router.add_delete("/api/history/{sid}", history_delete)
    studio_api.register(app)
    if (APP_DIR / "assets").exists():
        app.router.add_static("/assets/", APP_DIR / "assets")
    if (APP_DIR / "avatar3d").exists():
        app.router.add_static("/avatar3d/", APP_DIR / "avatar3d")
    return app


def main() -> None:
    page = f"http://localhost:{PORT}"
    # A fresh address each start, so the browser can't show a stale cached page.
    open_url = f"{page}/?v={int(datetime.datetime.now().timestamp())}"
    print(f"AI Interview Coach running at {page}  (keep this window open; close it to stop)")
    webbrowser.open(open_url)
    web.run_app(make_app(), host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
