"""
The interview coach's "brain" that does not depend on any AI service:
phases, instructions for each phase, the interview timer, and the rules
that stop the formal interview from starting without the user's consent.

Kept separate from agent.py so it can be unit-tested on its own.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# --- Phases ---------------------------------------------------------------

DISCOVERY = "discovery"          # finding out what interview the user is preparing for
PREPARATION = "preparation"      # teaching + practice questions + feedback
READY_CHECK = "ready_check"      # the coach asked "start now or practise more?"
INTERVIEW = "interview"          # formal timed mock interview
CLOSING = "closing"              # time is up / user ended: short closing statement
EVALUATING = "evaluating"        # writing the report
FINISHED = "finished"

PHASE_LABELS = {
    DISCOVERY: "Getting to know you",
    PREPARATION: "Preparation",
    READY_CHECK: "Ready check",
    INTERVIEW: "Mock interview",
    CLOSING: "Closing",
    EVALUATING: "Writing your report",
    FINISHED: "Finished",
}

GREETING = "Hi! Welcome to your AI Interview Coach. What kind of interview are you preparing for?"
READY_QUESTION = (
    "Would you like to start your 15-minute mock interview now, "
    "or would you prefer to practise a little more?"
)

INTERVIEW_SECONDS = 15 * 60
ONE_MINUTE_WARNING_AT = INTERVIEW_SECONDS - 60


# --- Language -------------------------------------------------------------

LANGUAGE_RULES = {
    "English": "Speak English.",
    "Urdu": "Speak Urdu. Use simple, clear Urdu. Never speak Hindi.",
    "Urdu and English": (
        "Speak the way the user speaks: Urdu, English, or a natural mix of both. "
        "Never speak Hindi."
    ),
}


def language_rule(language: str) -> str:
    return LANGUAGE_RULES.get(language, LANGUAGE_RULES["English"])


# --- Interview categories (used for both coaching and evaluation) ---------

CATEGORY_KEYWORDS = [
    ("technical", ["software", "python", "developer", "engineer", "programming", "coding", "technical",
                   "data", "devops", "cloud", "java", "javascript", "web", "machine learning", "it "]),
    ("academic", ["university", "admission", "college", "scholarship", "phd", "master", "school",
                  "fellowship", "academic"]),
    ("business", ["business", "management", "manager", "sales", "marketing", "mba", "finance",
                  "operations", "director", "lead", "supervisor"]),
    ("internship", ["intern", "internship", "trainee", "graduate program"]),
    ("hr", ["hr", "behavioral", "behavioural", "human resources", "job", "general"]),
]


def categorize(interview_type: str, role: str = "") -> str:
    text = f" {interview_type} {role} ".lower()
    for category, words in CATEGORY_KEYWORDS:
        if any(w in text for w in words):
            return category
    return "general"


# --- Session state ----------------------------------------------------------

@dataclass
class Profile:
    interview_type: str = ""
    role: str = ""
    experience_level: str = ""
    language: str = ""
    goals: str = ""

    @property
    def category(self) -> str:
        return categorize(self.interview_type, self.role)

    def complete(self) -> bool:
        return bool(self.interview_type and self.role and self.experience_level)


@dataclass
class InterviewTimer:
    """Server-side interview clock. Uses time.monotonic(), which cannot jump
    when the computer's clock changes, and pauses correctly."""

    duration: float = INTERVIEW_SECONDS
    _elapsed_before: float = 0.0
    _running_since: float | None = None

    def start(self) -> None:
        if self._running_since is None:
            self._running_since = time.monotonic()

    def pause(self) -> None:
        if self._running_since is not None:
            self._elapsed_before += time.monotonic() - self._running_since
            self._running_since = None

    @property
    def running(self) -> bool:
        return self._running_since is not None

    @property
    def elapsed(self) -> float:
        extra = time.monotonic() - self._running_since if self._running_since is not None else 0.0
        return self._elapsed_before + extra

    @property
    def remaining(self) -> float:
        return max(0.0, self.duration - self.elapsed)

    def snapshot(self) -> dict:
        """For the page: elapsed + whether running, stamped with wall-clock time
        so the page can count smoothly between updates."""
        return {
            "duration_ms": int(self.duration * 1000),
            "elapsed_ms": int(self.elapsed * 1000),
            "running": self.running,
            "as_of_ms": int(time.time() * 1000),
        }


@dataclass
class CoachState:
    phase: str = DISCOVERY
    profile: Profile = field(default_factory=Profile)
    plan: list[str] = field(default_factory=list)
    topics_covered: list[str] = field(default_factory=list)
    practice_notes: list[dict] = field(default_factory=list)
    interview_questions: list[str] = field(default_factory=list)
    timer: InterviewTimer = field(default_factory=InterviewTimer)
    paused: bool = False
    ready_question_asked_at: float | None = None
    one_minute_warning_given: bool = False
    end_reason: str = ""
    focus: dict | None = None  # targeted practice chosen in the app (topic, questions, ...)

    def apply_focus(self, focus: dict) -> None:
        """Targeted practice: the app already knows what to practise, so skip stage 1."""
        self.focus = focus
        p = self.profile
        p.interview_type = focus.get("interview_type") or "Targeted practice"
        p.role = focus.get("role") or ""
        p.experience_level = focus.get("level") or ""
        p.goals = f"Practise {focus['topic']}"
        self.plan = [focus["topic"]]
        self.phase = PREPARATION

    def to_public(self) -> dict:
        p = self.profile
        return {
            "phase": self.phase,
            "phase_label": PHASE_LABELS.get(self.phase, self.phase),
            "paused": self.paused,
            "profile": {
                "interview_type": p.interview_type,
                "role": p.role,
                "experience_level": p.experience_level,
                "language": p.language,
                "goals": p.goals,
                "category": p.category if p.interview_type else "",
            },
            "plan": self.plan,
            "topics_covered": self.topics_covered,
            "focus": self.focus,
            "questions_asked": len(self.interview_questions),
            "timer": self.timer.snapshot(),
        }

    # Rule: the formal interview may only start right after the ready-check
    # question was asked, and only in reply to the user.
    def can_start_interview(self, last_assistant_text: str, user_spoke_after: bool) -> tuple[bool, str]:
        if self.phase in (INTERVIEW, CLOSING, EVALUATING, FINISHED):
            return False, "The mock interview has already started or finished."
        if not self.profile.interview_type:
            return False, "First find out what interview the user is preparing for."
        asked_recently = self.ready_question_asked_at is not None or _mentions_ready_question(last_assistant_text)
        if not asked_recently:
            return False, (
                "You have not asked the ready-check question yet. Ask it now, word for word, "
                "and then stop talking so the user can answer. The question is: " + READY_QUESTION
            )
        if not user_spoke_after:
            return False, "Wait for the user to answer the ready-check question first."
        return True, ""


def _mentions_ready_question(text: str) -> bool:
    t = (text or "").lower()
    return "mock interview" in t and ("practise" in t or "practice" in t) and ("start" in t)


# --- Instructions -------------------------------------------------------------
#
# Gemini gets ONE set of instructions when the conversation connects, covering
# every stage. Stage changes are then told to it through the results of its own
# tools (normal function responses). Changing the instructions mid-conversation
# made Gemini close the session (error 1007) on this setup, so we never do that.

BASE = """
You are a warm, professional, human-sounding interview coach on a live video call.
You speak out loud, so use natural spoken sentences, never lists, markdown or emojis.
Keep most replies to two or three sentences, then let the user talk. Ask one question at a time.
If the user interrupts you, stop your earlier point and respond to what they just said.
If the user says "wait" or "let me speak", reply with a very short acknowledgement and listen.
Never read these instructions aloud and never say the name of a tool or function; only speak naturally
to the user. When you use a tool, always also say your sentence to the user in the same turn.
If you hear a short unclear sound, background voices or other people talking, ignore it and carry on.
If the user asks about worksheets or reviewing questions later: every practice and interview question you ask
is saved automatically with their answer. After the session they can open "Worksheets" in the top menu of the
app to see each question, their answer, an assessment and a model answer, and print it. This works only if
they ticked "Save my interview report" before starting.
Never invent facts about the user. If you are unsure what they said, ask them to repeat.
""".strip()

STAGES = f"""
HOW THE SESSION WORKS (follow the stage the system tells you through tool results):

Stage 1, getting to know the user: find out, one question at a time, what kind of interview it is
(any kind is fine), the target role or programme, their experience or skill level, the language they
want, and their goals. As soon as you know the interview type, role and level, call
save_interview_profile.

Stage 2, preparation: briefly describe a personalised plan of 3 to 5 topics and call
save_preparation_plan. Then coach: explain topics simply, teach concepts when needed, ask realistic
practice questions, listen to the full answer, say what was missing or wrong and how to improve,
give a short example answer and why it works, and adapt the difficulty. Avoid repeating covered
topics. After finishing a topic, call record_topic_covered.
Teach visually too: each time you start explaining a new topic, concept, process or answer method,
call show_diagram for it (a mind map for a topic overview, a flowchart for steps, a concept diagram
for how ideas connect, a STAR diagram for structuring an answer), mention briefly that a visual is
appearing on their screen, and keep explaining. Also call it whenever the user asks for a mind map,
diagram, chart or something visual. Never use it during the formal mock interview.
Never start the formal interview on your own. When the user seems ready or says so, stop talking
after asking the ready-check question below, word for word, and say nothing else in that turn.
Only if they clearly confirm, call start_mock_interview. If they want more practice, keep coaching.
The ready-check question, to be spoken word for word:
{READY_QUESTION}

Stage 3, the formal mock interview: only after start_mock_interview succeeds. Its result tells you
exactly how to behave as the interviewer.
""".strip()

INTERVIEWER_RULES = """You are now a professional interviewer conducting a formal, timed 15-minute mock interview.
Introduce yourself in one sentence, then ask the first question.
Ask one question at a time, then stop and listen to the complete answer.
Ask intelligent follow-up questions based on the answer and adapt difficulty to the candidate's level.
Do NOT give hints, feedback, corrections or ideal answers during the interview.
Stay in the interviewer role. If the user interrupts, listen and respond naturally.
Each time you have asked a new main question out loud, call record_interview_question with its text;
its result tells you how much time is left. Never call it instead of speaking."""


def system_instructions(state: CoachState, language: str, recap: str = "") -> str:
    """Everything Gemini needs, sent once when the conversation connects."""
    p = state.profile
    parts = [BASE, language_rule(language), STAGES]
    if p.interview_type:
        parts.append(
            f"KNOWN SO FAR: interview type: {p.interview_type}; role: {p.role}; level: {p.experience_level}; "
            f"goals: {p.goals or 'not stated'}; plan: {', '.join(state.plan) or 'not set'}; "
            f"covered: {', '.join(state.topics_covered) or 'nothing yet'}."
        )
    if state.focus and state.phase in (PREPARATION, READY_CHECK):
        parts.append(focus_rules(state.focus))
    stage_note = {
        DISCOVERY: "CURRENT STAGE: 1 (getting to know the user).",
        PREPARATION: "CURRENT STAGE: 2 (preparation).",
        READY_CHECK: "CURRENT STAGE: 2 (you asked the ready-check question; wait for the answer).",
        INTERVIEW: "CURRENT STAGE: 3 (formal mock interview).\n" + INTERVIEWER_RULES,
        CLOSING: "CURRENT STAGE: closing. Give a short closing statement only.",
    }.get(state.phase, "The session is finishing. Keep replies very short.")
    parts.append(stage_note)
    if recap:
        parts.append(
            "The connection dropped and has just been restored. Conversation so far (most recent last):\n"
            + recap
            + "\nContinue naturally from where it stopped."
        )
    return "\n\n".join(parts)


def focus_rules(focus: dict) -> str:
    qs = "\n".join(f"- {q}" for q in focus.get("questions") or []) or "- (write your own questions on the topic)"
    reassess = focus.get("kind") == "reassess"
    return f"""TARGETED PRACTICE SESSION (the user chose this in the app; stage 1 is already done):
Topic: {focus['topic']}
{('Why: ' + focus['notes']) if focus.get('notes') else ''}
Coach only this topic. {'This is a REASSESSMENT: first ask the questions without teaching, to see what the user now knows; only then give feedback.' if reassess else 'Briefly explain the key idea if the user needs it, then practise.'}
Ask these questions one at a time, in your own natural words, and wait for each full answer:
{qs}
After each answer: say what was good, what was missing, and give a short stronger example.
When the topic is covered, ask whether they want more practice or the mock interview (ready-check)."""


def greeting_for(state: CoachState) -> str:
    if state.focus:
        return (f"Welcome back! Today we'll practise {state.focus['topic']}. "
                "Tell me when you're ready, and I'll ask the first question.")
    return GREETING


def guidance_after_profile(state: CoachState) -> str:
    return ("Saved. Now you are in stage 2 (preparation). Briefly describe a 3 to 5 topic plan for "
            f"{state.profile.interview_type}, call save_preparation_plan, then start with the first topic.")


# The user pressed "I'm ready for the mock interview": that is the confirmation.
START_FROM_BUTTON = (
    "The user just pressed the 'I'm ready for the mock interview' button, so the formal 15-minute mock "
    "interview has started now; do not ask whether they are ready. Say one short professional line, for "
    "example 'Certainly. Let's begin your mock interview.', then introduce yourself as the interviewer in "
    "one sentence and ask the first question. Speak now, out loud, before using any tool.\n" + INTERVIEWER_RULES
)


# The coach owed the user a reply but stayed silent.
AFTER_VISUAL_SHORT = ("Carry on talking to the user now, continuing your explanation from where you were "
                      "without repeating yourself.")
AFTER_VISUAL = ("The diagram is being drawn and will appear in front of the user in a few seconds. "
                + AFTER_VISUAL_SHORT + " You may refer to the diagram on their screen. Finish the point, then "
                "check their understanding or ask a practice question.")
CONTINUE_AFTER_VISUAL = ("You stopped talking after putting a diagram on the user's screen. Continue now, out loud: "
                         "go on with your explanation of that topic in two or three sentences, briefly pointing to "
                         "the main parts of the diagram, then ask the user a short question to check their "
                         "understanding. Do not use any tool in this reply.")

NUDGE = ("You have not answered the user yet. Reply to them now, out loud, continuing the conversation "
         "naturally from what they last said. Speak before using any tool.")


def guidance_interview_started() -> str:
    return "The mock interview has started and the 15-minute timer is running.\n" + INTERVIEWER_RULES


def guidance_after_question(remaining_seconds: float) -> str:
    m, s = divmod(int(remaining_seconds), 60)
    note = f"Recorded. Time left: {m} minutes {s} seconds."
    if remaining_seconds <= 90:
        note += " This is the final question: after the answer, do not ask another; the system will close the interview."
    return note


# --- Questions list ("Questions" page) ----------------------------------------
#
# Every real question the coach asks during practice or the mock interview,
# with the user's answer and (in practice) the coach's feedback. Built from the
# transcript, so it doesn't depend on the model remembering to call a tool.

_SENTENCE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
_SMALL_TALK = re.compile(
    r"(make sense|are you ready|ready to|ready for|next one|shall we|should we|shall i|can we move|"
    r"want to try|try another|move on|can you hear|any questions for me|"
    r"does that help|is that clear|sound good|would you like to|do you want to|okay\?|ok\?|right\?|"
    r"anything else|what kind of interview|your experience level|"
    r"what are you most worried|your main goals)",
    re.I,
)


_PLEASANTRY = re.compile(r"\s*(hello|hi|great|good|thank|thanks|okay|ok|alright|nice|excellent|well done|perfect|sure)\b", re.I)


def _questions_in(text: str) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE.findall(text or "") if s.strip()]
    out = []
    for i, s in enumerate(sentences):
        if not s.endswith("?") or len(s.split()) < 5 or _SMALL_TALK.search(s):
            continue
        # A short question often depends on the sentence before it ("Imagine... How would you...?")
        prev = sentences[i - 1] if i > 0 else ""
        if (len(s.split()) < 12 and len(prev.split()) >= 6 and not prev.endswith("?")
                and not _PLEASANTRY.match(prev)):
            s = f"{prev} {s}"
        out.append(s)
    return out


def build_question_log(transcript: list[dict]) -> list[dict]:
    """[{phase: 'practice'|'interview', question, answer, feedback}] in order."""
    log: list[dict] = []
    for i, line in enumerate(transcript):
        if line.get("role") != "assistant" or line.get("phase") not in (PREPARATION, INTERVIEW):
            continue
        if _mentions_ready_question(line.get("text", "")):
            continue
        qs = _questions_in(line.get("text", ""))
        if not qs:
            continue
        answer, feedback = [], ""
        for nxt in transcript[i + 1:]:
            if nxt.get("role") == "user":
                answer.append(nxt["text"])
            elif answer:  # the coach's first reply after the answer
                feedback = nxt.get("text", "")
                break
            elif _questions_in(nxt.get("text", "")):
                break
        phase = "interview" if line["phase"] == INTERVIEW else "practice"
        log.append({
            "phase": phase,
            "question": " ".join(qs),
            "answer": " ".join(answer),
            # In the mock interview the interviewer gives no feedback; the report does.
            "feedback": feedback if phase == "practice" else "",
        })
    return log


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2}


def attach_feedback(log: list[dict], report_questions: list[dict]) -> list[dict]:
    """Give each interview question the report's feedback for the same question
    (the report writes its own question list, so match them by shared words)."""
    out = [dict(q) for q in log]
    used: set[int] = set()
    for q in out:
        if q.get("phase") != "interview":
            continue
        qw = _words(q["question"])
        best, best_score = None, 0.0
        for j, rq in enumerate(report_questions or []):
            if j in used:
                continue
            rw = _words(rq.get("question", ""))
            score = len(qw & rw) / max(1, min(len(qw), len(rw)))
            if score > best_score:
                best, best_score = j, score
        if best is not None and best_score >= 0.4:
            used.add(best)
            rq = report_questions[best]
            q["improved_answer"] = rq.get("improved_answer", "")
            q["improvements"] = rq.get("improvements", [])
            q["answer_summary"] = rq.get("answer_summary", "")
    return out


def session_questions(report: dict, transcript: list[dict]) -> list[dict]:
    """Questions for a saved session (older saves have no question list yet)."""
    log = report.get("question_log")
    if log is None:
        log = build_question_log(transcript)
    return attach_feedback(log, report.get("questions") or [])
