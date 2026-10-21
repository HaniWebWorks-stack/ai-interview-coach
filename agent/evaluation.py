"""
Interview evaluation: turns the interview transcript into a structured report
using a Gemini text model (free tier), with different criteria for different
kinds of interview.

Rules given to the model (and checked in code where possible):
- Judge only what is in the transcript. Never invent facts about the user.
- Separate objectively checkable errors (e.g. a wrong technical fact) from
  subjective communication feedback.
- If there is not enough evidence for a score, say so.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger("coach.evaluation")

# Current free-tier models (October 2026). Google retired gemini-2.0-flash and
# blocked the 2.5 text models for new users, so those are only last resorts.
EVAL_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
# Worksheets: the quick model first (a few seconds); bigger ones only as backup.
WORKSHEET_MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]
# Caption clean-up must be quick, so the small model goes first.
SCRIPT_FIX_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]

_clients: dict[str, genai.Client] = {}
MODEL_TIMEOUT = 75  # seconds per model before trying the next one


def fast_thinking(model: str) -> types.ThinkingConfig | None:
    """Gemini 3 Flash models think at 'medium' by default, which made one report
    take 3 minutes. 'low' is plenty for a report and much faster."""
    if model.startswith(("gemini-3.8-flash", "gemini-3.6-flash")):
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    return None


async def get_client(api_key: str) -> genai.Client:
    """Create the Google client once, in a worker thread: creating it loads SSL
    certificates, which froze the voice for about 2.5 seconds when done inline."""
    if api_key not in _clients:
        _clients[api_key] = await asyncio.to_thread(genai.Client, api_key=api_key)
    return _clients[api_key]

RUBRICS: dict[str, dict] = {
    "technical": {
        "label": "Technical interview",
        "criteria": [
            "Technical correctness",
            "Problem-solving approach",
            "Depth of knowledge",
            "Explaining technical ideas clearly",
            "Use of concrete examples",
        ],
        "guidance": "Check technical statements for factual correctness. Wrong facts, wrong code "
                    "behaviour or wrong complexity are objective errors.",
    },
    "academic": {
        "label": "University / scholarship interview",
        "criteria": [
            "Clarity of motivation and goals",
            "Evidence of achievements",
            "Fit with the programme",
            "Authentic personal story",
            "Communication and confidence",
        ],
        "guidance": "Focus on motivation, fit and evidence. Most feedback here is subjective; "
                    "objective errors are rare (e.g. contradicting themselves).",
    },
    "business": {
        "label": "Business / management interview",
        "criteria": [
            "Business and commercial understanding",
            "Leadership and people management",
            "Results backed by numbers",
            "Strategic thinking",
            "Structured communication",
        ],
        "guidance": "Reward specific results with numbers and clear situation-action-result stories.",
    },
    "internship": {
        "label": "Internship interview",
        "criteria": [
            "Motivation and interest in the role",
            "Relevant skills or coursework",
            "Willingness and ability to learn",
            "Examples from projects or studies",
            "Communication",
        ],
        "guidance": "Judge potential and learning ability more than experience.",
    },
    "hr": {
        "label": "HR / behavioural interview",
        "criteria": [
            "Relevance of answers",
            "Structure (situation, task, action, result)",
            "Use of concrete examples",
            "Self-awareness",
            "Motivation and culture fit",
            "Communication",
        ],
        "guidance": "Behavioural answers are mostly judged subjectively; look for concrete examples.",
    },
    "general": {
        "label": "General interview",
        "criteria": ["Relevance", "Clarity", "Structure", "Completeness", "Use of examples"],
        "guidance": "Judge answers against what the question asked.",
    },
}


class CriterionScore(BaseModel):
    name: str
    score: int = Field(description="1 (weak) to 5 (excellent), or 0 if not enough evidence")
    comment: str


class QuestionFeedback(BaseModel):
    question: str
    answer_summary: str = Field(description="What the user actually said, briefly. 'No answer given' if none.")
    relevance: int = Field(description="1-5, or 0 if no answer")
    correctness: int = Field(description="1-5 for factual/technical correctness, or 0 if not applicable")
    clarity_structure: int = Field(description="1-5")
    completeness: int = Field(description="1-5")
    objective_errors: list[str] = Field(description="Only clearly verifiable mistakes. Empty if none.")
    subjective_feedback: list[str] = Field(description="Communication/style opinions, labelled as opinions.")
    strengths: list[str]
    improvements: list[str]
    improved_answer: str = Field(description="A short example of a stronger spoken answer.")
    skipped: bool = Field(default=False, description="True if the candidate did not really answer (e.g. 'I don't know').")
    difficulty: str = Field(default="medium", description="easy, medium or hard, for this candidate's level")


class PlanItem(BaseModel):
    topic: str
    why: str
    how_to_practise: str


class Report(BaseModel):
    overall_score: int = Field(description="0-100")
    overall_summary: str
    criteria: list[CriterionScore]
    questions: list[QuestionFeedback]
    strengths: list[str]
    areas_to_improve: list[str]
    preparation_plan: list[PlanItem]
    evidence_note: str = Field(description="Limits of this evaluation, e.g. short interview or unclear audio.")
    confidence: str = Field(default="medium", description="high, medium or low: how much evidence supports these scores")


def build_prompt(profile: dict, transcript: list[dict], category: str, minutes: float, end_reason: str) -> str:
    rubric = RUBRICS.get(category, RUBRICS["general"])
    lines = []
    for t in transcript:
        who = "INTERVIEWER" if t["role"] == "assistant" else "CANDIDATE"
        cut = " [interviewer was interrupted here]" if t.get("interrupted") else ""
        lines.append(f"{who}: {t['text']}{cut}")
    convo = "\n".join(lines) or "(no conversation recorded)"
    return f"""You are an expert interview assessor. Evaluate this mock interview.

Interview type: {profile.get('interview_type')}  (category: {rubric['label']})
Role/programme: {profile.get('role')}
Candidate level: {profile.get('experience_level')}
Candidate goals: {profile.get('goals') or 'not stated'}
Duration: {minutes:.1f} minutes. How it ended: {end_reason}.

Use exactly these criteria (score each 1-5, or 0 if there is not enough evidence):
{chr(10).join('- ' + c for c in rubric['criteria'])}
Guidance: {rubric['guidance']}

Strict rules:
- Base everything ONLY on the transcript below. Do not invent anything the candidate did not say.
- The transcript comes from automatic speech recognition and may contain recognition mistakes;
  do not punish obvious recognition errors.
- Put only clearly verifiable mistakes in objective_errors. Opinions about style go in
  subjective_feedback and must be phrased as opinions.
- Give one entry in "questions" per main interviewer question, in order.
- If the interview was very short, say so in evidence_note and keep scores cautious.
- Fairness: never treat accent, nationality, gender, disability, a non-native speaking style, speaking
  slowly or needing time to think as evidence of poor competence. Judge the content of the answers.
- Mark a question as skipped when the candidate did not really answer it; do not invent an answer for it.
- Take question difficulty into account. Set confidence to low when there are only one or two answers,
  medium for a normal short interview, high only when there is plenty of evidence.
- These scores are an AI estimate for practice, not an objective or validated measurement; do not use
  wording that suggests otherwise.
- Write the report in clear, simple English.

TRANSCRIPT:
{convo}
"""


async def evaluate(api_key: str, profile: dict, transcript: list[dict], category: str,
                   minutes: float, end_reason: str) -> dict:
    """Returns a report dict, or a dict with 'error' if every model failed."""
    if not any(t.get("role") == "user" and len((t.get("text") or "").split()) >= 3 for t in transcript):
        # Nothing to score: say so straight away instead of asking Gemini.
        return {"error": "The mock interview ended before you answered any questions, so there is nothing "
                         "to score yet. Start a new mock interview and answer a few questions.",
                "error_kind": "empty"}
    client = await get_client(api_key)
    prompt = build_prompt(profile, transcript, category, minutes, end_reason)
    last_error = ""
    for model in EVAL_MODELS:
        try:
            resp = await asyncio.wait_for(client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Report,
                    temperature=0.3,
                    thinking_config=fast_thinking(model),
                ),
            ), timeout=MODEL_TIMEOUT)
            report = resp.parsed if isinstance(resp.parsed, Report) else Report.model_validate_json(resp.text)
            data = clean_report(report.model_dump())
            data["model"] = model
            data["category"] = category
            data["category_label"] = RUBRICS.get(category, RUBRICS["general"])["label"]
            return data
        except Exception as e:  # try the next model
            last_error = f"{model}: {type(e).__name__}: {e}"
            logger.warning("evaluation failed with %s", last_error)
    return {"error": f"Could not create the report. Last error: {last_error}"}


def clean_report(data: dict) -> dict:
    """Keep scores inside their allowed ranges whatever the model returned."""
    data["overall_score"] = max(0, min(100, int(data.get("overall_score", 0))))
    if data.get("confidence") not in ("high", "medium", "low"):
        data["confidence"] = "medium"
    for c in data.get("criteria", []):
        c["score"] = max(0, min(5, int(c.get("score", 0))))
    for q in data.get("questions", []):
        for k in ("relevance", "correctness", "clarity_structure", "completeness"):
            q[k] = max(0, min(5, int(q.get(k, 0))))
        if q.get("difficulty") not in ("easy", "medium", "hard"):
            q["difficulty"] = "medium"
        q["skipped"] = bool(q.get("skipped", False))
    return data


# --- Caption script fix ----------------------------------------------------

DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def needs_script_fix(text: str) -> bool:
    return bool(DEVANAGARI.search(text or ""))


async def fix_script(api_key: str, text: str, language: str) -> str | None:
    """Gemini's speech recognition often writes spoken Urdu in Hindi (Devanagari)
    script. Rewrite it in Urdu script (Urdu setting) or Roman Urdu (otherwise),
    without changing the words. Returns None if it fails."""
    target = "Urdu script (Nastaliq)" if language == "Urdu" else "Roman Urdu (Latin letters)"
    prompt = (
        f"Rewrite this speech transcript in {target}. Keep exactly the same words and meaning; "
        "keep English words in English. Return only the rewritten text.\n\n" + text
    )
    client = await get_client(api_key)
    for model in SCRIPT_FIX_MODELS:
        try:
            resp = await asyncio.wait_for(client.aio.models.generate_content(
                model=model, contents=prompt, config=types.GenerateContentConfig(temperature=0)
            ), timeout=20)
            out = (resp.text or "").strip()
            if out:
                return out
        except Exception as e:
            logger.warning("script fix failed with %s: %s", model, e)
    return None


def report_to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False)


# --- Worksheet (Worksheets page) --------------------------------------------
#
# For every question asked in a session: an assessment of the user's answer,
# a model answer and key points to remember. Written once, the first time the
# worksheet is opened, then saved with the session.

VERDICTS = ["strong", "good", "partly", "needs_work", "not_answered"]


class WorksheetItem(BaseModel):
    verdict: str = Field(description="One of: strong, good, partly, needs_work, not_answered")
    assessment: str = Field(description="One or two sentences on the candidate's answer: what was right, what was missing.")
    model_answer: str = Field(description="A strong spoken answer, 60-150 words, realistic for the candidate's level.")
    key_points: list[str] = Field(description="3 to 5 short points the answer must cover.")


class Worksheet(BaseModel):
    items: list[WorksheetItem]


def worksheet_prompt(profile: dict, questions: list[dict]) -> str:
    lines = []
    for i, q in enumerate(questions, 1):
        stage = "practice" if q.get("phase") == "practice" else "mock interview"
        lines.append(f"Q{i} ({stage}): {q.get('question', '')}\nCANDIDATE ANSWER: {q.get('answer') or '(no answer)'}")
    return f"""You are an expert interview coach writing a study worksheet for a candidate.
Interview: {profile.get('interview_type') or 'not stated'}; role: {profile.get('role') or 'not stated'};
level: {profile.get('experience_level') or 'not stated'}.

For EACH question below, in the same order (exactly {len(questions)} items), give:
- verdict: strong, good, partly, needs_work, or not_answered (use not_answered if there is no real answer,
  e.g. "I don't know");
- assessment: one or two honest, kind sentences about the candidate's answer;
- model_answer: a strong answer the candidate could say out loud, suited to their level, 60-150 words,
  plain sentences, no markdown; for behavioural questions use a short situation-task-action-result story
  with a realistic placeholder where personal details are needed;
- key_points: 3 to 5 short points a good answer must cover.
Be factually correct. Write in the same language as the question. The speech-to-text may contain errors,
so judge the meaning, not the spelling.

QUESTIONS:
{chr(10).join(lines)}
"""


async def worksheet(api_key: str, profile: dict, questions: list[dict]) -> list[dict]:
    """Returns one item per question (raises if every model failed)."""
    if not questions:
        return []
    if not api_key:
        raise RuntimeError("No Google API key is saved on this laptop (run save-gemini-key.bat).")
    client = await get_client(api_key)
    prompt = worksheet_prompt(profile, questions)
    last_error = ""
    for model in WORKSHEET_MODELS:
        try:
            resp = await asyncio.wait_for(client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=Worksheet, temperature=0.3,
                    thinking_config=fast_thinking(model),
                ),
            ), timeout=MODEL_TIMEOUT)
            ws = resp.parsed if isinstance(resp.parsed, Worksheet) else Worksheet.model_validate_json(resp.text)
            return clean_worksheet([i.model_dump() for i in ws.items], len(questions))
        except Exception as e:
            last_error = f"{model}: {type(e).__name__}: {e}"
            logger.warning("worksheet failed with %s", last_error)
    raise RuntimeError(f"Could not write the worksheet. Last error: {last_error}")


def clean_worksheet(items: list[dict], count: int) -> list[dict]:
    """Exactly one item per question, with a known verdict."""
    out = []
    for i in range(count):
        it = dict(items[i]) if i < len(items) else {}
        verdict = str(it.get("verdict", "")).strip().lower().replace(" ", "_").replace("-", "_")
        out.append({
            "verdict": verdict if verdict in VERDICTS else "partly",
            "assessment": it.get("assessment", "") or "",
            "model_answer": it.get("model_answer", "") or "",
            "key_points": [p for p in (it.get("key_points") or []) if p][:5],
        })
    return out
