"""
AI Interview Coach - the voice + avatar agent.

What it does, in plain words:
- Talks with you in real time (Google Gemini Live, free tier) and shows a
  lip-synced human avatar (LiveAvatar). You can interrupt at any moment:
  the voice and the face stop and the coach listens.
- Goes through the stages from the project brief:
  discovery -> personalised preparation -> ready check -> 15-minute mock
  interview (server-side timer) -> closing -> evaluation report.
- The formal interview can only start after the coach has asked the ready
  question and you have answered (enforced in code, not just in the prompt).
- If the avatar's free time runs out, the conversation continues by voice.
- Sends live state (stage, timer, plan, transcript, report) to the web page.

Started by run-coach.bat ("dev" mode, with the web page) or
run-voice-test.bat ("console" mode: voice only, laptop mic/speakers).
"""

import asyncio
import datetime
import json
import logging
import os
import pathlib
import socket
import sys
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import Agent, AgentServer, AgentSession, RunContext, function_tool
from livekit.agents.llm import ToolResult
from livekit.agents.voice.io import _AudioSinkProxy
from livekit.plugins import google, liveavatar, openai

import coach_logic as cl
import evaluation
import storage
import studio

# Secret keys are kept OUTSIDE the OneDrive project folder.
APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
load_dotenv(APP_DATA / "agent.env")
# Non-secret settings (model, voice, avatar, language) live in the project.
SETTINGS_FILE = pathlib.Path(__file__).resolve().parent / "settings.env"
WAYNE_SANDBOX_AVATAR = "dd73ea75-1218-4ef3-92ce-606d5f7fbc0a"
AVATAR_IDENTITY = "liveavatar-avatar-agent"
AVATAR_START_TIMEOUT = 20  # seconds; after this the coach starts by voice

PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "logs"


GEMINI_LIVE_DEFAULT = "gemini-3.8-live"
GEMINI_LIVE_OLD = "gemini-2.5-flash-native-audio-preview-12-2025"


def load_settings() -> SimpleNamespace:
    """Re-read settings.env at the start of every session, so changes made on
    the Settings page are used without restarting anything."""
    load_dotenv(SETTINGS_FILE, override=True)
    provider = os.getenv("VOICE_PROVIDER", "gemini").strip().lower()
    if provider == "openai":
        model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
        voice = os.getenv("OPENAI_REALTIME_VOICE", "marin")
    else:
        provider = "gemini"
        model = os.getenv("GEMINI_LIVE_MODEL", GEMINI_LIVE_DEFAULT)
        # The 2.5 preview model randomly closes sessions with error 1007 (a
        # known Google bug), so an old setting is moved to the stable model.
        if model == GEMINI_LIVE_OLD:
            model = GEMINI_LIVE_DEFAULT
        voice = os.getenv("GEMINI_VOICE", "Kore")
    avatar_id = os.getenv("LIVEAVATAR_AVATAR_ID", WAYNE_SANDBOX_AVATAR)
    return SimpleNamespace(
        provider=provider,
        model=model,
        voice=voice,
        # Gemini's native-audio models pick the spoken language themselves and
        # ignore a language code, so the language goes into the instructions.
        language=os.getenv("COACH_LANGUAGE", "English"),
        # 3d = free avatar drawn in the browser from the coach's voice (no
        # time limit); video = LiveAvatar (uses credits).
        avatar_mode=os.getenv("AVATAR_MODE", "3d").strip().lower(),
        avatar_enabled=(os.getenv("AVATAR_ENABLED", "false").strip().lower() == "true"
                        and os.getenv("AVATAR_MODE", "3d").strip().lower() == "video"),
        avatar_id=avatar_id,
        avatar_name=os.getenv("LIVEAVATAR_AVATAR_NAME", "Wayne"),
        avatar_sandbox=avatar_id == WAYNE_SANDBOX_AVATAR,
        avatar_quality=os.getenv("LIVEAVATAR_VIDEO_QUALITY", "medium"),
        turn_silence_ms=int(os.getenv("TURN_SILENCE_MS", "500")),
        # How long you must speak before the coach stops for you (barge-in).
        barge_in_ms=int(os.getenv("BARGE_IN_MS", "300")),
    )


S = load_settings()


def build_voice_model():
    """Real-time speech-to-speech model. Both providers have built-in barge-in."""
    if S.provider == "openai":
        return openai.realtime.RealtimeModel(model=S.model, voice=S.voice)
    from google.genai import types as gtypes

    return google.realtime.RealtimeModel(
        model=S.model,
        voice=S.voice,
        # Gemini decides you have finished speaking after a short silence
        # (default about 800 ms; Google recommends 500-800 ms).
        realtime_input_config=gtypes.RealtimeInputConfig(
            automatic_activity_detection=gtypes.AutomaticActivityDetection(
                silence_duration_ms=S.turn_silence_ms,
                # Fewer false interruptions: short noises and background voices
                # (other people in the room) no longer cut the coach off. Real
                # speech still interrupts her after about a third of a second.
                start_of_speech_sensitivity=gtypes.StartSensitivity.START_SENSITIVITY_LOW,
                prefix_padding_ms=S.barge_in_ms,
            )
        ),
        # Without compression Gemini ends audio sessions after 15 minutes;
        # with it, sessions can run as long as the user wants.
        context_window_compression=gtypes.ContextWindowCompressionConfig(
            sliding_window=gtypes.SlidingWindow(),
        ),
        # Lets the connector reconnect to the same conversation when Google
        # rotates the connection (about every 10 minutes).
        session_resumption=gtypes.SessionResumptionConfig(),
    )


# --- Logging ---------------------------------------------------------------

class EventLog:
    """Timestamped events in logs/voice-test-<time>.txt (plus a technical log)."""

    def __init__(self) -> None:
        LOG_DIR.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = LOG_DIR / f"voice-test-{stamp}.txt"
        self.debug_path = LOG_DIR / f"agent-debug-{stamp}.txt"
        _start_debug_log(self.debug_path)
        self.start = time.monotonic()
        self.write(
            f"provider={S.provider} model={S.model} voice={S.voice} language={S.language} "
            f"turn_silence_ms={S.turn_silence_ms}"
        )

    def write(self, message: str) -> None:
        line = f"[{time.monotonic() - self.start:8.2f}s] {message}"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _start_debug_log(path: pathlib.Path) -> None:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    for name in ("livekit.agents", "livekit.plugins.liveavatar", "livekit.plugins.google", "coach.evaluation"):
        logging.getLogger(name).setLevel(logging.INFO)


async def warm_up_dns(urls: list[str], log: EventLog, attempts: int = 15) -> None:
    """Looks up each server address, retrying for up to ~15 seconds. On this
    laptop Windows sometimes fails a lookup with a temporary error (11002);
    once it succeeds Windows caches the answer for the real connection."""
    loop = asyncio.get_running_loop()
    for url in urls:
        host = urlparse(url).hostname
        if not host:
            continue
        for attempt in range(1, attempts + 1):
            try:
                infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                ips = sorted({i[4][0] for i in infos})
                log.write(f"DNS ok: {host} (attempt {attempt}) -> {', '.join(ips[:2])}")
                break
            except socket.gaierror as e:
                log.write(f"DNS failed: {host} (attempt {attempt}): {e}")
                await asyncio.sleep(1)
        else:
            log.write(f"ERROR DNS: could not look up {host} after {attempts} attempts")


# --- Avatar ----------------------------------------------------------------

class LoggedAvatarSession(liveavatar.AvatarSession):
    """The official LiveAvatar connector, plus a record of every interruption
    and of how long the avatar takes to start talking."""

    WATCHED = {
        "agent.speak_started", "agent.speak_ended", "agent.speak_interrupted",
        "agent.audio_buffer_cleared", "error", "warning",
    }

    def __init__(self, log: EventLog, **kwargs) -> None:
        super().__init__(**kwargs)
        self._log = log
        self._interrupt_sent_at: float | None = None
        self._first_audio_at: float | None = None

    def send_event(self, msg: dict) -> None:
        if msg.get("type") == "agent.speak" and self._first_audio_at is None:
            self._first_audio_at = time.monotonic()
        super().send_event(msg)

    def _on_clear_buffer(self) -> None:
        if self._avatar_speaking:
            self._interrupt_sent_at = time.monotonic()
            self._log.write("AVATAR: interrupt command sent (face was talking)")
        super()._on_clear_buffer()

    def _handle_server_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "agent.speak_started" and self._first_audio_at is not None:
            self._log.write(f"TIMING: avatar started talking {time.monotonic() - self._first_audio_at:.2f}s after receiving the audio")
        if kind in ("agent.speak_ended", "agent.speak_interrupted"):
            self._first_audio_at = None
        if kind in self.WATCHED:
            detail = event.get("error") or event.get("warning") or ""
            self._log.write(f"AVATAR event: {kind} {detail}".rstrip())
            if kind in ("agent.speak_interrupted", "agent.audio_buffer_cleared") and self._interrupt_sent_at:
                delay = time.monotonic() - self._interrupt_sent_at
                self._log.write(f"AVATAR INTERRUPTION CONFIRMED: face + voice stopped {delay:.2f}s after the interrupt command")
                self._interrupt_sent_at = None
        super()._handle_server_event(event)


# --- The coach ------------------------------------------------------------

class Coach(Agent):
    """One agent for the whole session. Its instructions are set once when the
    conversation connects (all stages); stage changes reach Gemini through the
    results of these tools. Tools never change (that would force a reconnect)."""

    def __init__(self, ctl: "SessionController", recap: str = "") -> None:
        super().__init__(instructions=cl.system_instructions(ctl.state, S.language, recap))
        self.ctl = ctl

    @function_tool()
    async def save_interview_profile(
        self,
        context: RunContext,
        interview_type: str,
        role: str,
        experience_level: str,
        interview_language: str = "",
        goals: str = "",
    ) -> ToolResult:
        """Save what the user is preparing for. Call as soon as you know the interview type,
        the target role or programme, and the user's experience or skill level.

        Args:
            interview_type: Any kind of interview, in the user's words (e.g. "Python developer job").
            role: The target role, programme or scholarship.
            experience_level: e.g. "fresh graduate", "3 years", "intermediate".
            interview_language: Language the user wants for the interview, if mentioned.
            goals: The user's main goals or worries, if mentioned.
        """
        # Noted silently: the coach keeps talking normally, no extra turn.
        return ToolResult(await self.ctl.save_profile(interview_type, role, experience_level, interview_language, goals), reply_required=False)

    @function_tool()
    async def save_preparation_plan(self, context: RunContext, topics: list[str]) -> ToolResult:
        """Save the personalised preparation plan (3 to 5 short topic names) after describing it.

        Args:
            topics: Short topic names, e.g. ["Python data structures", "Tell me about yourself"].
        """
        # Noted silently: the coach keeps talking normally, no extra turn.
        return ToolResult(await self.ctl.save_plan(topics), reply_required=False)

    @function_tool()
    async def record_topic_covered(self, context: RunContext, topic: str) -> ToolResult:
        """Record that a preparation topic has been covered, to avoid repeating it.

        Args:
            topic: Short topic name.
        """
        # Noted silently: the coach keeps talking normally, no extra turn.
        return ToolResult(await self.ctl.topic_covered(topic), reply_required=False)

    @function_tool()
    async def show_diagram(self, context: RunContext, topic: str, diagram_type: str = "mindmap") -> ToolResult:
        """Put a visual diagram on the user's screen to support what you are explaining.
        Use it in preparation whenever you start explaining a topic, concept, process or answer
        method, and whenever the user asks for a mind map, diagram or visual. Keep talking normally
        while it is drawn; never read the diagram out node by node.

        Args:
            topic: What the diagram is about, e.g. "Python data structures" or "Answering 'tell me about yourself'".
            diagram_type: One of "mindmap" (overview of a topic), "concept" (how ideas relate),
                "flowchart" (a process or steps), "star" (how to structure an answer).
        """
        # Drawn in the background. The result asks Gemini to carry on talking (a tool call
        # ends its turn), and a short safety check nudges it if it still goes quiet.
        return ToolResult(await self.ctl.show_diagram(topic, diagram_type), reply_required=True)

    @function_tool()
    async def start_mock_interview(self, context: RunContext) -> str:
        """Start the formal timed 15-minute mock interview. Only call this after you asked the
        ready-check question AND the user clearly said they want to start now."""
        return await self.ctl.start_interview()

    @function_tool()
    async def record_interview_question(self, context: RunContext, question: str) -> ToolResult:
        """During the mock interview, record each new main question you ask.

        Args:
            question: The question text.
        """
        # Noted silently: the coach keeps talking normally, no extra turn.
        return ToolResult(await self.ctl.record_question(question), reply_required=False)

    @function_tool()
    async def end_mock_interview_early(self, context: RunContext) -> ToolResult:
        """End the mock interview early, only when the user clearly asks to stop the interview."""
        # Noted silently: the coach keeps talking normally, no extra turn.
        return ToolResult(await self.ctl.request_end("ended early by the user (spoken request)"), reply_required=False)


class SessionController:
    """Holds the session state and does everything around the conversation:
    stages, timer, transcript, avatar fallback, page updates, evaluation, and
    automatic recovery if Google closes the voice connection with an error."""

    MAX_RESTARTS = 3

    def __init__(self, ctx: agents.JobContext, log: EventLog) -> None:
        self.ctx = ctx
        self.session: AgentSession | None = None
        self.log = log
        self.state = cl.CoachState()
        self.coach: Coach | None = None
        self.session_id = uuid.uuid4().hex[:12]
        self.save_history = False
        self.transcript: list[dict] = []
        self.last_user_at = 0.0
        self.avatar: LoggedAvatarSession | None = None
        self.avatar_status = "3d" if S.avatar_mode == "3d" else "off"
        self.avatar_closing = False
        self.avatar_reason = ""
        self.room_audio_tail = None
        self.end_task: asyncio.Task | None = None
        self.bg: set[asyncio.Task] = set()
        self.restarts = 0
        self.user_gone = False
        self.saved = False
        self.started_at = time.monotonic()
        self.questions_sent = 0
        self.avatar_shown = asyncio.Event()  # the page says the 3D interviewer is visible
        self.awaiting_reply_since: float | None = None
        self.nudged = False
        self.diagram_topics: set[str] = set()
        self.diagram_jobs = 0

    # ----- helpers
    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.bg.add(task)
        task.add_done_callback(self.bg.discard)
        return task

    async def publish(self) -> None:
        data = self.state.to_public()
        data["avatar"] = {"status": self.avatar_status,
                          "name": "3D interviewer" if S.avatar_mode == "3d" else S.avatar_name, "sandbox": S.avatar_sandbox,
                          "reason": self.avatar_reason}
        data["session_id"] = self.session_id
        data["save_history"] = self.save_history
        try:
            await self.ctx.room.local_participant.set_attributes({"coach.state": json.dumps(data)})
        except Exception as e:  # console mode has no real room
            self.log.write(f"(state not published: {type(e).__name__})")

    async def send(self, topic: str, payload: dict) -> None:
        try:
            await self.ctx.room.local_participant.send_text(
                json.dumps(payload, ensure_ascii=False), topic=topic, compress=False
            )
        except Exception as e:
            self.log.write(f"(could not send {topic}: {type(e).__name__})")

    async def set_phase(self, phase: str) -> None:
        if self.state.phase == phase:
            return
        self.log.write(f"STAGE: {self.state.phase} -> {phase}")
        self.state.phase = phase
        await self.publish()

    # ----- the voice conversation (started again automatically after an error)
    async def start_conversation(self, recap: str = "") -> None:
        session = AgentSession(llm=build_voice_model())
        self.session = session
        self.coach = Coach(self, recap)
        log = self.log

        @session.on("agent_state_changed")
        def _agent_state(ev) -> None:
            log.write(f"AI state: {ev.old_state} -> {ev.new_state}")
            if ev.new_state == "speaking" and session is self.session:
                self.awaiting_reply_since = None  # she is answering

        @session.on("user_state_changed")
        def _user_state(ev) -> None:
            log.write(f"USER state: {ev.old_state} -> {ev.new_state}")

        @session.on("conversation_item_added")
        def _item(ev) -> None:
            self.on_item(ev.item)

        @session.on("function_tools_executed")
        def _tools(ev) -> None:
            log.write(f"TOOLS used: {[c.name for c in getattr(ev, 'function_calls', [])]}")

        @session.on("error")
        def _error(ev) -> None:
            log.write(f"ERROR from {type(ev.source).__name__}: {ev.error}")

        @session.on("close")
        def _close(ev) -> None:
            log.write(f"SESSION CLOSED reason={ev.reason} error={ev.error}")
            if ev.error is not None and session is self.session and not self.user_gone:
                self.spawn(self.recover())

        await session.start(room=self.ctx.room, agent=self.coach)
        log.write("session started")
        if S.avatar_enabled:
            await self.start_avatar()
        elif S.avatar_mode == "3d":
            log.write("avatar: 3D avatar drawn in the browser (free, no time limit)")
        await self.publish()

    # ----- watchdog: the coach owes the user a reply but stays silent
    # (the voice model sometimes "thinks" forever, or answers with only a
    # background tool call and no words).
    NUDGE_AFTER = 6     # seconds of silence before a gentle nudge
    RECONNECT_AFTER = 15  # seconds before the voice connection is renewed

    def expect_reply(self) -> None:
        """Called when the coach should speak next (user finished, button pressed)."""
        if self.session is not None and self.session.agent_state != "speaking":
            self.awaiting_reply_since = time.monotonic()
            self.nudged = False

    async def reply_watchdog(self) -> None:
        while True:
            await asyncio.sleep(1)
            since = self.awaiting_reply_since
            session = self.session
            if since is None or session is None or self.state.paused or self.user_gone:
                continue
            if self.state.phase in (cl.CLOSING, cl.EVALUATING, cl.FINISHED):
                self.awaiting_reply_since = None
                continue
            if session.agent_state == "speaking" or session.user_state == "speaking":
                continue
            waited = time.monotonic() - since
            if waited >= self.RECONNECT_AFTER:
                self.awaiting_reply_since = None
                self.log.write(f"SILENT: no reply for {waited:.0f}s - reconnecting the voice")
                await self.restart_voice("the coach stopped responding")
            elif waited >= self.NUDGE_AFTER and not self.nudged:
                self.nudged = True
                self.log.write(f"SILENT: no reply for {waited:.0f}s - nudging the coach")
                opening = self.state.phase == cl.INTERVIEW and not any(
                    t["role"] == "assistant" and t["phase"] == cl.INTERVIEW for t in self.transcript)
                try:
                    session.generate_reply(instructions=cl.START_FROM_BUTTON if opening else cl.NUDGE)
                except Exception as e:
                    self.log.write(f"nudge failed: {type(e).__name__}: {e}")

    async def restart_voice(self, why: str) -> None:
        """Close the frozen voice connection and continue with a fresh one."""
        old = self.session
        self.session = None  # so its close event doesn't trigger a second recovery
        try:
            if old is not None:
                await asyncio.wait_for(old.aclose(), timeout=8)
        except Exception as e:
            self.log.write(f"(closing frozen session: {type(e).__name__})")
        self.session = old
        await self.recover(reason=why)

    def recap(self, lines: int = 16) -> str:
        out = []
        for t in self.transcript[-lines:]:
            who = "User" if t["role"] == "user" else "You"
            out.append(f"{who}: {t['text']}")
        return "\n".join(out)

    async def recover(self, reason: str = "error") -> None:
        """Google closed (or froze) the voice connection: reconnect and carry on."""
        if self.restarts >= self.MAX_RESTARTS:
            self.log.write("RECOVERY: too many errors, not restarting again")
            await self.send("coach.notice", {"text": "The voice connection failed repeatedly. Please leave and start a new session."})
            return
        self.restarts += 1
        # Second error on the same model: try the other Gemini voice model.
        if reason == "error" and self.restarts >= 2 and S.provider == "gemini":
            other = GEMINI_LIVE_OLD if S.model != GEMINI_LIVE_OLD else GEMINI_LIVE_DEFAULT
            self.log.write(f"RECOVERY: switching voice model {S.model} -> {other}")
            S.model = other
        self.log.write(f"RECOVERY: restarting the conversation (attempt {self.restarts}, model {S.model})")
        await self.send("coach.notice", {"text": "The connection dropped. Reconnecting…"})
        await asyncio.sleep(1)
        self.avatar = None
        self.avatar_status = "3d" if S.avatar_mode == "3d" else "off"
        try:
            await self.start_conversation(recap=self.recap())
            if self.state.phase == cl.INTERVIEW and not self.state.interview_questions:
                # The interview had just started: begin it properly.
                self.session.generate_reply(instructions=cl.START_FROM_BUTTON)
            else:
                self.session.generate_reply(
                    instructions="The connection dropped for a moment and is now back. Say briefly: "
                                 "'Sorry, I lost the connection for a moment.' Then continue exactly where you left off."
                )
            await self.send("coach.notice", {"text": ""})
        except Exception as e:
            self.log.write(f"RECOVERY failed: {type(e).__name__}: {e}")

    # ----- tools
    async def save_profile(self, itype, role, level, lang, goals) -> str:
        p = self.state.profile
        p.interview_type, p.role, p.experience_level = itype.strip(), role.strip(), level.strip()
        p.language = lang.strip() or S.language
        p.goals = goals.strip()
        self.log.write(f"PROFILE: {itype} | {role} | {level} | category={p.category}")
        if self.state.phase == cl.DISCOVERY:
            await self.set_phase(cl.PREPARATION)
        else:
            await self.publish()
        return cl.guidance_after_profile(self.state)

    async def save_plan(self, topics: list[str]) -> str:
        self.state.plan = [t.strip() for t in topics if t.strip()][:6]
        self.log.write(f"PLAN: {self.state.plan}")
        await self.publish()
        return "Plan saved. Start with the first topic."

    async def topic_covered(self, topic: str) -> str:
        if topic and topic.strip() not in self.state.topics_covered:
            self.state.topics_covered.append(topic.strip())
            await self.publish()
        covered = ", ".join(self.state.topics_covered)
        return f"Recorded. Topics covered so far: {covered}. Move on to a topic not yet covered."

    async def show_diagram(self, topic: str, kind: str) -> str:
        """Draw a diagram in the background and send it to the page (coach.diagram)."""
        topic = " ".join(str(topic or "").split())[:160]
        kind = kind if kind in ("mindmap", "concept", "flowchart", "star") else "mindmap"
        if self.state.phase in (cl.INTERVIEW, cl.CLOSING, cl.EVALUATING, cl.FINISHED):
            return "Diagrams are not shown during the formal interview. Continue as the interviewer."
        if not topic:
            return "No topic was given. " + cl.AFTER_VISUAL_SHORT
        key = f"{kind}:{topic.lower()}"
        if key in self.diagram_topics:
            return "That diagram is already on the user's screen. " + cl.AFTER_VISUAL_SHORT
        if self.diagram_jobs >= 2:
            return "Another diagram is still being drawn. " + cl.AFTER_VISUAL_SHORT
        self.diagram_topics.add(key)
        self.diagram_jobs += 1
        did = "dia-" + uuid.uuid4().hex[:12]
        self.log.write(f"DIAGRAM: {kind} about {topic!r}")
        await self.send("coach.diagram", {"id": did, "status": "pending", "topic": topic, "kind": kind})
        self.spawn(self._draw_diagram(did, topic, kind, key))
        self.spawn(self.keep_talking_after_visual())
        return cl.AFTER_VISUAL

    VISUAL_SILENCE = 3.0  # seconds of quiet after a diagram before the coach is reminded to go on

    async def keep_talking_after_visual(self) -> None:
        """Gemini's turn ends with a tool call. If the coach then stays quiet (and the user
        is not talking), remind her to continue the explanation she started."""
        t0 = time.monotonic()
        quiet_since: float | None = None
        while time.monotonic() - t0 < 45:
            await asyncio.sleep(0.25)
            session = self.session
            if session is None or self.user_gone or self.state.paused or self.state.phase != cl.PREPARATION:
                return
            if self.last_user_at > t0 or session.user_state == "speaking":
                return  # the user took the turn; normal conversation continues
            if session.agent_state == "speaking":
                if quiet_since is not None:
                    return  # she carried on by herself
                continue  # still finishing the sentence before the tool call
            if quiet_since is None:
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= self.VISUAL_SILENCE:
                self.log.write("SILENT after diagram - asking the coach to continue")
                try:
                    session.generate_reply(instructions=cl.CONTINUE_AFTER_VISUAL)
                except Exception as e:
                    self.log.write(f"continue failed: {type(e).__name__}: {e}")
                self.expect_reply()  # the normal watchdog takes over from here
                return

    async def _draw_diagram(self, did: str, topic: str, kind: str, key: str) -> None:
        p = self.state.profile
        context = "; ".join(x for x in (
            f"Interview: {p.interview_type}" if p.interview_type else "",
            f"Role: {p.role}" if p.role else "",
            f"Level: {p.experience_level}" if p.experience_level else "") if x)
        try:
            data = await studio.make_diagram(os.getenv("GOOGLE_API_KEY", ""), kind, topic, context,
                                             models=studio.FAST_MODELS)
            saved = False
            if self.save_history:
                try:
                    await asyncio.to_thread(storage.save_material, did, "diagram", data["title"],
                                            {"kind": kind, "topic": topic, "source": {"type": "session", "id": self.session_id}}, data)
                    saved = True
                except Exception as e:
                    self.log.write(f"(diagram not saved: {type(e).__name__})")
            await self.send("coach.diagram", {"id": did, "status": "ready", "topic": topic, "kind": kind,
                                              "saved": saved, "diagram": data})
            self.log.write(f"DIAGRAM ready: {data['title']!r} ({len(data['nodes'])} parts)")
        except Exception as e:
            self.diagram_topics.discard(key)  # allow a retry later
            msg = str(e) if isinstance(e, studio.StudioError) else "The diagram could not be drawn."
            self.log.write(f"DIAGRAM failed: {type(e).__name__}")
            await self.send("coach.diagram", {"id": did, "status": "error", "topic": topic, "kind": kind, "error": msg})
        finally:
            self.diagram_jobs -= 1

    async def start_interview(self) -> str:
        last_assistant = next((t["text"] for t in reversed(self.transcript) if t["role"] == "assistant"), "")
        asked_at = self.state.ready_question_asked_at or 0
        ok, why = self.state.can_start_interview(last_assistant, self.last_user_at > asked_at)
        if not ok:
            self.log.write(f"START REFUSED: {why}")
            return f"Not started. {why}"
        await self.begin_interview()
        return cl.guidance_interview_started()

    async def begin_interview(self) -> None:
        """Start the 15-minute mock interview (server-side timer)."""
        self.state.interview_questions.clear()
        self.state.timer = cl.InterviewTimer()
        self.state.timer.start()
        await self.set_phase(cl.INTERVIEW)
        self.spawn(self.timer_loop())

    async def record_question(self, question: str) -> str:
        if self.state.phase != cl.INTERVIEW:
            return "Noted. This is practice, not the mock interview, so there is no clock. Wait for the user's answer."
        if question.strip():
            self.state.interview_questions.append(question.strip())
            await self.publish()
        return cl.guidance_after_question(self.state.timer.remaining)

    async def request_end(self, reason: str) -> str:
        if self.state.phase != cl.INTERVIEW:
            return "There is no mock interview running."
        if self.end_task is None:
            self.end_task = self.spawn(self.end_interview(reason))
        return "Ending the interview now."

    # ----- interview timer (authoritative, server side)
    async def timer_loop(self) -> None:
        while self.state.phase == cl.INTERVIEW:
            await asyncio.sleep(1)
            if self.state.timer.running and self.state.timer.remaining <= 0:
                self.log.write("TIMER: 15 minutes reached")
                await self.request_end("time limit reached (15 minutes)")
                return

    async def end_interview(self, reason: str) -> None:
        st = self.state
        st.timer.pause()
        st.end_reason = reason
        minutes = st.timer.elapsed / 60
        await self.set_phase(cl.CLOSING)
        session = self.session
        try:
            session.interrupt()
            handle = session.generate_reply(
                instructions="The interview is over. Give a short, friendly two-sentence closing statement: "
                             "thank the user and say their feedback report is being prepared. Ask no questions. "
                             "Do not call any tools."
            )
            await asyncio.wait_for(handle.wait_for_playout(), timeout=25)
        except Exception as e:
            self.log.write(f"closing statement problem: {type(e).__name__}: {e}")

        await self.set_phase(cl.EVALUATING)
        try:
            session.input.set_audio_enabled(False)
        except Exception:
            pass
        await self.close_avatar()  # stop using avatar credits while the report is written

        interview_lines = [t for t in self.transcript if t["phase"] in (cl.INTERVIEW, cl.CLOSING)]
        profile = self.state.to_public()["profile"]
        self.log.write(f"EVALUATION: {len(interview_lines)} lines, {minutes:.1f} min, reason={reason}")
        report = await evaluation.evaluate(
            os.getenv("GOOGLE_API_KEY", ""), profile, interview_lines, st.profile.category, minutes, reason
        )
        report["session_id"] = self.session_id
        report["minutes"] = round(minutes, 1)
        report["end_reason"] = reason
        report["profile"] = profile
        report["question_log"] = cl.build_question_log(self.transcript)
        if self.state.focus:
            report["focus"] = self.state.focus
        saved = False
        if "error" not in report and self.save_history:
            try:
                storage.save_session(self.session_id, profile, st.profile.category, minutes, reason,
                                     report, interview_lines)
                saved = True
                self.saved = True
            except Exception as e:
                self.log.write(f"ERROR saving history: {type(e).__name__}: {e}")
        report["saved"] = saved
        self.log.write(f"EVALUATION done: score={report.get('overall_score')} saved={saved} error={report.get('error')}")
        await self.send("coach.report", report)
        await self.set_phase(cl.FINISHED)

    # ----- pause / resume / ready (buttons on the page)
    async def pause(self) -> str:
        if self.state.paused or self.state.phase in (cl.CLOSING, cl.EVALUATING, cl.FINISHED):
            return "ignored"
        self.state.paused = True
        self.state.timer.pause()
        self.session.interrupt()
        self.session.input.set_audio_enabled(False)
        self.log.write("PAUSED")
        await self.publish()
        return "paused"

    async def resume(self, speak: bool = True) -> str:
        if not self.state.paused:
            return "ignored"
        self.state.paused = False
        self.session.input.set_audio_enabled(True)
        if self.state.phase == cl.INTERVIEW:
            self.state.timer.start()
        self.log.write("RESUMED")
        await self.publish()
        if speak:
            self.session.generate_reply(
                instructions="The user has resumed after a pause. In one short sentence, welcome them back "
                             "and continue exactly where you left off."
            )
        return "resumed"

    async def ready_pressed(self) -> str:
        if self.state.phase not in (cl.DISCOVERY, cl.PREPARATION, cl.READY_CHECK):
            return "ignored"
        if not self.state.profile.interview_type:
            self.session.generate_reply(
                instructions="The user pressed the 'I'm ready' button, but you do not yet know what interview "
                             "they are preparing for. Briefly say you need that first and ask what kind of "
                             "interview it is, plus the role and their experience level."
            )
            return "need-profile"
        # Pressing the button IS the user's confirmation: start straight away,
        # with no "are you ready?" question.
        self.log.write("READY BUTTON: user confirmed - starting the mock interview")
        if self.state.paused:
            await self.resume(speak=False)  # the user may have paused before pressing the button
        try:
            self.session.interrupt()
        except Exception:
            pass
        await self.begin_interview()
        self.spawn(self._open_interview())
        return "started"

    async def _open_interview(self) -> None:
        """The interviewer's first words. If she stays silent (or only calls a
        tool), the reply watchdog nudges her and, if needed, reconnects."""
        self.expect_reply()
        try:
            self.session.generate_reply(instructions=cl.START_FROM_BUTTON)
        except Exception as e:
            self.log.write(f"interview opening request failed: {type(e).__name__}: {e}")

    # ----- transcript
    def on_item(self, item) -> None:
        role = getattr(item, "role", None)
        text = (getattr(item, "text_content", None) or "").strip()
        if role not in ("user", "assistant") or not text:
            return
        rec = {
            "id": getattr(item, "id", uuid.uuid4().hex),
            "role": role,
            "text": text,
            "phase": self.state.phase,
            "interrupted": bool(getattr(item, "interrupted", False)),
            "t": round(time.time(), 2),
        }
        self.transcript.append(rec)
        flag = "  <<INTERRUPTED - memory trimmed to what was heard>>" if rec["interrupted"] else ""
        self.log.write(f"MEMORY {role}: {text!r}{flag}")
        if role == "user":
            self.last_user_at = time.monotonic()
            self.expect_reply()
            if evaluation.needs_script_fix(text):
                self.spawn(self.fix_caption(rec))
        elif role == "assistant" and self.state.phase in (cl.DISCOVERY, cl.PREPARATION) \
                and cl._mentions_ready_question(text):
            self.state.ready_question_asked_at = time.monotonic()
            self.spawn(self.set_phase(cl.READY_CHECK))
        self.spawn(self.send("coach.transcript", rec))
        if rec["phase"] in (cl.PREPARATION, cl.INTERVIEW):
            self.spawn(self.send_questions())

    async def send_questions(self) -> None:
        """The page's "Questions" tab: every question asked so far, with answers."""
        await self.send("coach.questions", {"questions": cl.build_question_log(self.transcript)})

    async def save_practice_only(self) -> None:
        """Session ended without a mock interview: keep the practice questions
        (only if the user agreed to saving)."""
        if self.saved or not self.save_history:
            return
        log = cl.build_question_log(self.transcript)
        if not log:
            return
        minutes = (time.monotonic() - self.started_at) / 60
        profile = self.state.to_public()["profile"]
        report = {"kind": "practice", "question_log": log, "profile": profile, "focus": self.state.focus,
                  "minutes": round(minutes, 1), "end_reason": "practice session (no mock interview)"}
        try:
            storage.save_session(self.session_id, profile, self.state.profile.category, minutes,
                                 report["end_reason"], report, self.transcript)
            self.saved = True
            self.log.write(f"PRACTICE saved: {len(log)} questions")
        except Exception as e:
            self.log.write(f"ERROR saving practice: {type(e).__name__}: {e}")

    async def fix_caption(self, rec: dict) -> None:
        fixed = await evaluation.fix_script(os.getenv("GOOGLE_API_KEY", ""), rec["text"], S.language)
        if fixed:
            rec["raw_text"], rec["text"] = rec["text"], fixed
            await self.send("coach.transcript", rec)

    # ----- avatar with automatic voice-only fallback
    def find_room_audio_tail(self) -> None:
        self.room_audio_tail = None
        cur = self.session.output.audio
        while cur is not None:
            if isinstance(cur, _AudioSinkProxy):
                self.room_audio_tail = cur.next_in_chain
                return
            cur = cur.next_in_chain

    async def liveavatar_credits(self) -> float | None:
        """Credits left on the LiveAvatar account (None if it can't be checked)."""
        import aiohttp

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http:
                async with http.get(
                    "https://api.liveavatar.com/v1/users/credits",
                    headers={"X-API-KEY": os.getenv("LIVEAVATAR_API_KEY", ""), "accept": "application/json"},
                ) as r:
                    if r.status != 200:
                        return None
                    data = (await r.json()).get("data") or {}
                    return float(data.get("credits_left"))
        except Exception:
            return None

    async def start_avatar(self) -> None:
        """Start the avatar, but never let it hold up the conversation:
        no credits -> voice mode at once; no face within the time limit -> voice mode."""
        self.find_room_audio_tail()
        self.log.write(f"avatar: {S.avatar_name} id={S.avatar_id} sandbox={S.avatar_sandbox} quality={S.avatar_quality}")
        self.avatar_status = "starting"
        self.avatar_reason = ""
        await self.publish()

        if not S.avatar_sandbox:
            credits = await self.liveavatar_credits()
            self.log.write(f"avatar: credits left = {credits}")
            if credits is not None and credits < 1:
                self.avatar_status = "unavailable"
                self.avatar_reason = "no_credits"
                self.log.write("avatar skipped: no LiveAvatar credits left - continuing by voice")
                await self.publish()
                return

        avatar = None
        try:
            avatar = LoggedAvatarSession(self.log, avatar_id=S.avatar_id, is_sandbox=S.avatar_sandbox,
                                         video_quality=S.avatar_quality)
            await asyncio.wait_for(avatar.start(self.session, room=self.ctx.room), timeout=AVATAR_START_TIMEOUT)
            self.avatar = avatar
            await avatar.wait_for_join(timeout=AVATAR_START_TIMEOUT)
            self.avatar_status = "on"
            self.log.write("avatar: on screen")
        except Exception as e:
            reason = "timeout" if isinstance(e, asyncio.TimeoutError) else "error"
            self.log.write(f"avatar unavailable ({reason}), continuing by voice: {type(e).__name__}: {e}")
            self.avatar_status = "unavailable"
            self.avatar_reason = reason
            self.restore_voice_output()
            if avatar is not None:
                try:
                    await asyncio.wait_for(avatar.aclose(), timeout=5)
                except Exception:
                    pass
        await self.publish()

    def restore_voice_output(self) -> None:
        if self.room_audio_tail is not None and self.session is not None:
            self.session.output.replace_audio_tail(self.room_audio_tail)
            self.log.write("voice output restored to the room (voice-only mode)")

    def on_participant_left(self, p: rtc.RemoteParticipant) -> None:
        if p.identity == AVATAR_IDENTITY and self.avatar_status == "on":
            self.avatar_status = "closed" if self.avatar_closing else "ended"
            if not self.avatar_closing:
                self.log.write("avatar left (free time or credits used up) - continuing by voice")
            self.restore_voice_output()
            self.spawn(self.publish())
        elif p.identity != AVATAR_IDENTITY and p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            self.user_gone = True

    async def close_avatar(self) -> None:
        if self.avatar is not None and self.avatar_status == "on":
            self.avatar_closing = True
            try:
                await self.avatar.aclose()
            except Exception as e:
                self.log.write(f"avatar close problem: {type(e).__name__}")


# --- Entry point -------------------------------------------------------------

def prewarm(proc: agents.JobProcess) -> None:
    """Runs once when a worker process starts, before any session: loads the
    slow parts (Windows certificate store, tool modules) so they no longer
    freeze the first seconds of a session (it was 4.7 s)."""
    import ssl

    ssl.create_default_context()
    import livekit.agents.llm.async_toolset  # noqa: F401


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session(agent_name="interview-coach")
async def entrypoint(ctx: agents.JobContext) -> None:
    global S
    S = load_settings()
    log = EventLog()
    await warm_up_dns([ctx._info.url, os.getenv("LIVEKIT_URL", "")], log)

    ctl = SessionController(ctx, log)
    ctx.room.on("participant_disconnected", ctl.on_participant_left)
    # Prepare the Google client for captions/report in the background now,
    # so it never freezes the voice later.
    ctl.spawn(evaluation.get_client(os.getenv("GOOGLE_API_KEY", "")))

    # Consent sent by the page (participant metadata).
    try:
        await ctx.connect()
        user = await asyncio.wait_for(ctx.wait_for_participant(), timeout=20)
        meta = json.loads(user.metadata or "{}")
        ctl.save_history = bool(meta.get("save_history", False))
        if isinstance(meta.get("focus"), dict) and meta["focus"].get("topic"):
            ctl.state.apply_focus(meta["focus"])
            log.write(f"TARGETED PRACTICE: {meta['focus']['topic']} ({meta['focus'].get('kind')})")
        log.write(f"user joined: save_history={ctl.save_history}")
    except Exception as e:
        log.write(f"(no user metadata: {type(e).__name__})")

    # Buttons on the page call these (LiveKit RPC).
    async def rpc_pause(data: rtc.RpcInvocationData) -> str:
        return await ctl.pause()

    async def rpc_resume(data: rtc.RpcInvocationData) -> str:
        return await ctl.resume()

    async def rpc_ready(data: rtc.RpcInvocationData) -> str:
        return await ctl.ready_pressed()

    async def rpc_end(data: rtc.RpcInvocationData) -> str:
        return await ctl.request_end("ended early by the user (End button)")

    async def rpc_avatar_ready(data: rtc.RpcInvocationData) -> str:
        if not ctl.avatar_shown.is_set():
            log.write("avatar: 3D interviewer is on screen")
        ctl.avatar_shown.set()
        return "ok"

    lp = ctx.room.local_participant
    try:
        lp.register_rpc_method("coach.pause", rpc_pause)
        lp.register_rpc_method("coach.resume", rpc_resume)
        lp.register_rpc_method("coach.ready", rpc_ready)
        lp.register_rpc_method("coach.end_interview", rpc_end)
        lp.register_rpc_method("coach.avatar_ready", rpc_avatar_ready)
    except Exception as e:
        log.write(f"(RPC not available: {type(e).__name__})")

    async def _finish_eval_on_shutdown() -> None:
        if ctl.end_task is not None and not ctl.end_task.done():
            await asyncio.wait({ctl.end_task}, timeout=60)
        await ctl.save_practice_only()

    ctx.add_shutdown_callback(_finish_eval_on_shutdown)

    await ctl.start_conversation()
    ctl.spawn(ctl.reply_watchdog())

    # 3D interviewer: say hello only once she is on screen (she is normally
    # preloaded, so this is instant; never wait more than 20 seconds).
    if S.avatar_mode == "3d" and not ctl.user_gone:
        waited = time.monotonic()
        try:
            await asyncio.wait_for(ctl.avatar_shown.wait(), timeout=20)
            log.write(f"greeting waited {time.monotonic() - waited:.1f}s for the 3D interviewer")
        except asyncio.TimeoutError:
            log.write("3D interviewer not confirmed within 20s - greeting anyway")

    # Greeting (repeated once if a background noise cut it off before any word was heard).
    for attempt in (1, 2):
        try:
            handle = ctl.session.generate_reply(
                instructions=f'Greet the user with exactly: "{cl.greeting_for(ctl.state)}"')
            log.write(f"greeting requested (attempt {attempt})")
            await asyncio.wait_for(handle.wait_for_playout(), timeout=30)
            log.write(f"greeting finished (interrupted={handle.interrupted})")
        except Exception as e:
            log.write(f"ERROR greeting: {type(e).__name__}: {e}")
            break
        if any(t["role"] == "assistant" for t in ctl.transcript) or attempt == 2:
            break
        await asyncio.sleep(1.5)
        if ctl.session.user_state == "speaking" or any(t["role"] == "assistant" for t in ctl.transcript):
            break
        log.write("greeting was cut off before anything was heard - repeating it")


# --- Console mode helpers (run-voice-test.bat) ------------------------------

def _only_one_copy():
    """Stops a second copy from running at the same time."""
    APP_DATA.mkdir(parents=True, exist_ok=True)
    handle = open(APP_DATA / "voice-test.lock", "a+")
    try:
        import msvcrt
    except ImportError:  # not Windows
        return handle
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("Another coach window is already running. Close it first, then try again.")
        sys.exit(1)
    return handle


def _add_saved_audio_devices() -> None:
    """Use the microphone/speaker chosen by diagnose-voice.bat, if any (console mode)."""
    if sys.argv[1:] != ["console"]:
        return
    from audio_devices import find_device_index

    for env_name, flag, kind in (
        ("VOICE_INPUT_DEVICE", "--input-device", "input"),
        ("VOICE_OUTPUT_DEVICE", "--output-device", "output"),
    ):
        name = os.getenv(env_name, "")
        if name:
            index = find_device_index(name, kind)
            if index is not None:
                sys.argv += [flag, str(index)]
                print(f"Using {kind} device: {name}")
            else:
                print(f"Saved {kind} device not found ({name}); using Windows default.")


if __name__ == "__main__":
    _lock = _only_one_copy()
    _add_saved_audio_devices()
    agents.cli.run_app(server)
