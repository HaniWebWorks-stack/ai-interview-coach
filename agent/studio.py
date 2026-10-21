"""
Preparation Studio: AI-generated study material built from the user's real
saved interview reports (Google Gemini, free tier, same key as the coach).

Every generator asks Gemini for structured JSON (a schema), then validates
and cleans it here before anything is shown or saved, so a malformed answer
can never break a diagram or invent fields. If Gemini is unavailable, the
error is returned honestly; nothing is faked.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field

import evaluation
from evaluation import RUBRICS, fast_thinking, get_client

logger = logging.getLogger("coach.studio")

STUDIO_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
FAST_MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]
TIMEOUT = 90


class StudioError(RuntimeError):
    """Gemini could not produce a usable result (message is safe to show)."""


def friendly_error(e: Exception) -> str:
    text = str(e)
    if "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return "Google's free usage limit was reached for now. Please try again in a few minutes."
    if "503" in text or "UNAVAILABLE" in text or "overloaded" in text.lower():
        return "Google's AI service is busy right now. Please try again in a moment."
    if "API key" in text or "401" in text or "403" in text or "PERMISSION_DENIED" in text:
        return "The Google API key was refused. Run save-gemini-key.bat to check it."
    if isinstance(e, asyncio.TimeoutError):
        return "Google's AI took too long to answer. Please try again."
    return "The AI could not create this right now. Please try again."


async def generate(api_key: str, prompt: str, schema: type[BaseModel] | None,
                   models: list[str] = STUDIO_MODELS, temperature: float = 0.3) -> Any:
    """Ask Gemini (trying the next model on failure). Returns parsed dict or text."""
    if not api_key:
        raise StudioError("No Google API key is saved on this laptop. Run save-gemini-key.bat first.")
    client = await get_client(api_key)
    last: Exception | None = None
    for model in models:
        try:
            cfg = types.GenerateContentConfig(temperature=temperature, thinking_config=fast_thinking(model))
            if schema is not None:
                cfg.response_mime_type = "application/json"
                cfg.response_schema = schema
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(model=model, contents=prompt, config=cfg), timeout=TIMEOUT)
            if schema is None:
                text = (resp.text or "").strip()
                if text:
                    return text
                raise StudioError("empty answer")
            parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text)
            return parsed.model_dump()
        except Exception as e:  # try the next model
            last = e
            logger.warning("studio generation failed with %s: %s", model, type(e).__name__)
    raise StudioError(friendly_error(last or RuntimeError("unknown")))


def _s(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _list(v: Any, n: int, each: int = 300) -> list[str]:
    return [_s(x, each) for x in (v or []) if _s(x, each)][:n]


# --- digest of real saved reports (the only input for personal analysis) -----

def digest_reports(sessions: list[dict], max_chars: int = 14_000) -> str:
    """Compact, factual summary of saved sessions (newest first) for prompts."""
    parts = []
    for s in sessions:
        r = s.get("report") or {}
        date = datetime.datetime.fromtimestamp(s.get("created_at") or 0).strftime("%Y-%m-%d")
        head = f"[{date}] {s.get('interview_type') or 'Interview'} | role: {s.get('role') or '-'} | " \
               f"category: {RUBRICS.get(s.get('category') or 'general', RUBRICS['general'])['label']}"
        if r.get("kind") == "practice":
            lines = [head + " | PRACTICE SESSION (not scored)"]
            ws = r.get("worksheet") or []
            for i, q in enumerate((r.get("question_log") or [])[:8]):
                verdict = ws[i].get("verdict") if i < len(ws) else ""
                lines.append(f"  Q: {_s(q.get('question'), 160)} | answer: {_s(q.get('answer'), 160) or '(none)'}"
                             + (f" | assessment: {verdict}" if verdict else ""))
        elif r.get("criteria"):
            lines = [head + f" | MOCK INTERVIEW score {r.get('overall_score')}/100 (AI estimate)"]
            lines.append("  criteria: " + "; ".join(f"{c['name']} {c['score']}/5" + (f" ({_s(c.get('comment'), 120)})" if c.get('comment') else "")
                                                    for c in r.get("criteria", []) if c.get("score")))
            if r.get("areas_to_improve"):
                lines.append("  to improve: " + "; ".join(_list(r["areas_to_improve"], 5, 160)))
            if r.get("strengths"):
                lines.append("  strengths: " + "; ".join(_list(r["strengths"], 4, 120)))
            for q in (r.get("questions") or [])[:8]:
                errs = "; ".join(_list(q.get("objective_errors"), 3, 120))
                lines.append(f"  Q: {_s(q.get('question'), 150)} | relevance {q.get('relevance')}, correctness "
                             f"{q.get('correctness')}, completeness {q.get('completeness')}, clarity "
                             f"{q.get('clarity_structure')}" + (" | SKIPPED" if q.get("skipped") else "")
                             + (f" | errors: {errs}" if errs else "")
                             + f" | answer: {_s(q.get('answer_summary'), 140)}")
        else:
            continue
        block = "\n".join(lines)
        if sum(len(p) for p in parts) + len(block) > max_chars:
            break
        parts.append(block)
    return "\n\n".join(parts)


# --- 1. Preparation engine: weaknesses, recommendations, reassessment --------

WEAKNESS_KINDS = ("knowledge_gap", "incomplete_answer", "weak_examples", "unclear_communication", "lacks_structure")


class Weakness(BaseModel):
    topic: str = Field(description="Short name of the concept or skill, e.g. 'Python decorators'")
    kind: str = Field(description="knowledge_gap, incomplete_answer, weak_examples, unclear_communication or lacks_structure")
    severity: str = Field(description="high, medium or low")
    evidence: str = Field(description="What in the reports shows this, with the session date. Only real evidence.")
    occurrences: int = Field(description="In how many sessions this appeared")
    why_it_matters: str
    revision_note: str = Field(description="A short, correct explanation of the concept or skill (3-6 sentences)")
    framework: str = Field(description="A simple way to structure answers on this topic")
    practice_questions: list[str] = Field(description="3 NEW questions, not copies of questions already asked")


class Strength(BaseModel):
    topic: str
    evidence: str


class Recommendation(BaseModel):
    title: str
    why: str
    action: str = Field(description="practice, study or diagram")
    topic: str


class Reassessment(BaseModel):
    topic: str = Field(description="A weakness from the previous analysis")
    status: str = Field(description="improved, still_weak or not_reassessed")
    evidence: str


class Insights(BaseModel):
    summary: str
    weaknesses: list[Weakness]
    strengths: list[Strength]
    recommendations: list[Recommendation]
    reassessment: list[Reassessment]


def insights_prompt(digest: str, previous: list[dict]) -> str:
    prev = "\n".join(f"- {w.get('topic')} ({w.get('kind')})" for w in previous) or "(none: this is the first analysis)"
    return f"""You are an expert interview coach analysing a candidate's real practice history.

SAVED SESSIONS (newest first; scores are AI estimates for practice):
{digest}

WEAKNESSES FOUND IN THE PREVIOUS ANALYSIS:
{prev}

Produce:
1. summary: 2-3 sentences on where the candidate stands now.
2. weaknesses (at most 6, most important first): recurring problems backed by the sessions above. For
   each, classify the kind precisely: knowledge_gap (did not know or got facts wrong), incomplete_answer
   (right direction but missing parts), weak_examples (no or vague examples), unclear_communication
   (hard to follow), lacks_structure (no clear order, e.g. no situation-task-action-result). Give the
   evidence with dates, a short correct revision note, an answer framework, and 3 NEW practice questions
   that test the same skill differently (never repeat a question that was already asked).
3. strengths: only skills with real evidence.
4. recommendations (3-5): what to practise next and why, most useful first.
5. reassessment: for each previous weakness, improved / still_weak / not_reassessed, based only on
   sessions after it was found. Use not_reassessed when there is no newer evidence.
Rules: use ONLY the evidence above; never invent sessions, scores or answers. If there is little data,
say so in the summary and keep the lists short. Judge content only, never accent or speaking style.
"""


def clean_insights(data: dict) -> dict:
    ws = []
    for i, w in enumerate((data.get("weaknesses") or [])[:6]):
        topic = _s(w.get("topic"), 80)
        if not topic:
            continue
        kind = w.get("kind") if w.get("kind") in WEAKNESS_KINDS else "incomplete_answer"
        ws.append({"id": f"w{i + 1}", "topic": topic, "kind": kind,
                   "severity": w.get("severity") if w.get("severity") in ("high", "medium", "low") else "medium",
                   "evidence": _s(w.get("evidence"), 500), "occurrences": max(1, int(w.get("occurrences") or 1)),
                   "why_it_matters": _s(w.get("why_it_matters"), 400), "revision_note": _s(w.get("revision_note"), 1200),
                   "framework": _s(w.get("framework"), 600), "practice_questions": _list(w.get("practice_questions"), 5)})
    recs = []
    for r in (data.get("recommendations") or [])[:5]:
        if _s(r.get("title"), 120):
            recs.append({"title": _s(r.get("title"), 120), "why": _s(r.get("why"), 400),
                         "action": r.get("action") if r.get("action") in ("practice", "study", "diagram") else "practice",
                         "topic": _s(r.get("topic") or r.get("title"), 80)})
    rea = []
    for r in (data.get("reassessment") or [])[:8]:
        if _s(r.get("topic"), 80):
            rea.append({"topic": _s(r.get("topic"), 80),
                        "status": r.get("status") if r.get("status") in ("improved", "still_weak", "not_reassessed") else "not_reassessed",
                        "evidence": _s(r.get("evidence"), 400)})
    return {"summary": _s(data.get("summary"), 800), "weaknesses": ws,
            "strengths": [{"topic": _s(x.get("topic"), 80), "evidence": _s(x.get("evidence"), 300)}
                          for x in (data.get("strengths") or [])[:6] if _s(x.get("topic"), 80)],
            "recommendations": recs, "reassessment": rea}


async def make_insights(api_key: str, sessions: list[dict], previous: list[dict]) -> dict:
    digest = digest_reports(sessions)
    if not digest:
        raise StudioError("There are no saved sessions to analyse yet. Save a practice session or mock interview first.")
    data = await generate(api_key, insights_prompt(digest, previous), Insights)
    return clean_insights(data)


# --- 2. Diagrams ---------------------------------------------------------------

DIAGRAM_KINDS = {
    "mindmap": ("Mind map", ("root", "branch", "leaf"), "leaf"),
    "concept": ("Concept diagram", ("concept", "example", "note"), "concept"),
    "flowchart": ("Process flowchart", ("start", "action", "decision", "end"), "action"),
    "skillgap": ("Skill-gap diagram", ("role", "group", "strength", "improve", "unassessed"), "unassessed"),
    "star": ("Answer structure", ("step", "guidance", "example"), "guidance"),
    "roadmap": ("Learning roadmap", ("milestone", "task"), "task"),
}

KIND_RULES = {
    "mindmap": "A mind map: exactly one 'root' node (the central topic), 4-7 'branch' nodes connected to "
               "the root, and 2-4 'leaf' nodes under each branch. Edges go root->branch->leaf.",
    "concept": "A concept diagram: 'concept' nodes for the ideas and 'example' nodes for concrete examples. "
               "Edges show real relationships with a short label (e.g. 'is used by', 'returns', 'example of').",
    "flowchart": "A process flowchart: one 'start' node, 'action' steps, 'decision' nodes (questions) whose "
                 "outgoing edges are labelled (e.g. 'yes'/'no'), and one or more 'end' nodes. Edges show order.",
    "skillgap": "A skill-gap diagram for the role: one 'role' node, then one node per skill the role needs. "
                "Use 'strength' ONLY if the sessions show clear evidence of it, 'improve' ONLY if they show a "
                "weakness, otherwise 'unassessed' (never call an unassessed skill a weakness). For strength and "
                "improve nodes, fill 'evidence' with what the sessions show.",
    "star": "An answer-structure diagram for the STAR method (or the most suitable framework for the topic): "
            "'step' nodes in order (Situation -> Task -> Action -> Result), each with 'guidance' and an "
            "'example' node written for this topic and role.",
    "roadmap": "A personalised learning roadmap: 'milestone' nodes in order, each with 2-4 'task' nodes "
               "(something concrete to read, practise or rehearse). Put 1-3 practice questions on each task.",
}


class DNode(BaseModel):
    id: str
    label: str = Field(description="Short label, max 6 words")
    detail: str = Field(description="1-3 sentence explanation shown when the node is opened")
    role: str
    evidence: str = Field(default="", description="Only for skill-gap strength/improve nodes")
    questions: list[str] = Field(default_factory=list, description="Optional practice questions for this node")


class DEdge(BaseModel):
    source: str
    target: str
    label: str = ""


class Diagram(BaseModel):
    title: str
    summary: str
    nodes: list[DNode]
    edges: list[DEdge]


def diagram_prompt(kind: str, topic: str, context: str) -> str:
    return f"""Create a learning diagram for interview preparation.

Topic: {topic}
Type: {DIAGRAM_KINDS[kind][0]}
{KIND_RULES[kind]}

Context about the candidate (use it to make the diagram relevant; do not invent facts about them):
{context or '(no personal context)'}

Rules: every statement must be factually correct; labels short (max 6 words); 'detail' explains the node
in plain language; ids are short unique strings; at most 30 nodes; every edge connects existing ids;
no decorative or filler nodes.
"""


class DiagramError(ValueError):
    pass


def clean_diagram(kind: str, data: dict) -> dict:
    """Validate and repair a diagram. Raises DiagramError if it cannot be used."""
    if kind not in DIAGRAM_KINDS:
        raise DiagramError("Unknown diagram type.")
    _, roles, default_role = DIAGRAM_KINDS[kind]
    nodes, ids = [], {}
    for n in (data.get("nodes") or [])[:40]:
        label = _s(n.get("label"), 70)
        if not label:
            continue
        raw_id = _s(n.get("id"), 40) or f"n{len(nodes)}"
        nid, k = raw_id, 2
        while nid in ids.values():
            nid = f"{raw_id}-{k}"
            k += 1
        ids.setdefault(raw_id, nid)
        role = n.get("role") if n.get("role") in roles else default_role
        evidence = _s(n.get("evidence"), 400)
        if kind == "skillgap" and role in ("strength", "improve") and not evidence:
            role = "unassessed"  # no evidence => not a confirmed strength or weakness
        nodes.append({"id": nid, "label": label, "detail": _s(n.get("detail"), 700), "role": role,
                      "evidence": evidence, "questions": _list(n.get("questions"), 4),
                      **({"importance": n["importance"]} if n.get("importance") else {})})
    if len(nodes) < 2:
        raise DiagramError("The AI returned a diagram with too few parts. Please try again.")
    valid = {n["id"] for n in nodes}
    edges, seen = [], set()
    for e in (data.get("edges") or [])[:80]:
        src = ids.get(_s(e.get("source"), 40), _s(e.get("source"), 40))
        tgt = ids.get(_s(e.get("target"), 40), _s(e.get("target"), 40))
        if src in valid and tgt in valid and src != tgt and (src, tgt) not in seen:
            seen.add((src, tgt))
            edges.append({"source": src, "target": tgt, "label": _s(e.get("label"), 40)})
    if kind == "mindmap":
        roots = [n for n in nodes if n["role"] == "root"]
        if not roots:
            nodes[0]["role"] = "root"
        for extra in roots[1:]:
            extra["role"] = "branch"
    if kind == "flowchart" and not any(n["role"] == "start" for n in nodes):
        nodes[0]["role"] = "start"
    if kind == "roadmap":
        for n in nodes:
            n.setdefault("status", "pending")
    # anything left unconnected is attached to the first node, so nothing floats alone
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    for n in nodes[1:]:
        if n["id"] not in connected:
            edges.append({"source": nodes[0]["id"], "target": n["id"], "label": ""})
    return {"kind": kind, "title": _s(data.get("title"), 120) or DIAGRAM_KINDS[kind][0],
            "summary": _s(data.get("summary"), 600), "nodes": nodes, "edges": edges}


async def make_diagram(api_key: str, kind: str, topic: str, context: str,
                       models: list[str] = STUDIO_MODELS) -> dict:
    if kind not in DIAGRAM_KINDS:
        raise StudioError("Unknown diagram type.")
    topic = _s(topic, 200)
    if not topic:
        raise StudioError("Please enter a topic for the diagram.")
    last = None
    for _ in range(2):  # one retry if the result is unusable
        data = await generate(api_key, diagram_prompt(kind, topic, context), Diagram, models=models)
        try:
            return clean_diagram(kind, data)
        except DiagramError as e:
            last = e
    raise StudioError(str(last))


# --- 3. Study pack -------------------------------------------------------------

class Note(BaseModel):
    heading: str
    body: str


class Definition(BaseModel):
    term: str
    meaning: str


class BankQuestion(BaseModel):
    question: str
    type: str = Field(description="technical, behavioral or situational")
    difficulty: str = Field(description="easy, medium or hard")
    model_answer: str
    key_points: list[str]


class QuizItem(BaseModel):
    question: str
    options: list[str] = Field(description="exactly 4 options")
    answer_index: int = Field(description="0-3, index of the correct option")
    explanation: str


class Flashcard(BaseModel):
    front: str
    back: str


class FrameworkStep(BaseModel):
    name: str
    guidance: str


class AnswerFramework(BaseModel):
    name: str
    steps: list[FrameworkStep]
    example: str


class StudyPack(BaseModel):
    title: str
    notes: list[Note]
    definitions: list[Definition]
    question_bank: list[BankQuestion]
    quiz: list[QuizItem]
    flashcards: list[Flashcard]
    frameworks: list[AnswerFramework]
    checklist: list[str]


def studypack_prompt(topic: str, context: str) -> str:
    return f"""Create a study pack for interview preparation on: {topic}

Candidate context (do not invent facts about them):
{context or '(no personal context)'}

Include: 3-6 revision notes (heading + 2-5 sentence body); 4-8 key definitions; a question bank of 6-10
realistic interview questions (mix technical/behavioral/situational as fits the topic) each with a model
answer (60-150 words, spoken style) and key points; a quiz of 5-8 multiple-choice questions with exactly 4
options, the correct answer_index and a one-sentence explanation; 8-12 flashcards; 1-2 answer frameworks
(e.g. STAR) with steps and an example for this topic; a 5-8 item revision checklist for the day before the
interview. Everything must be factually correct and suited to the candidate's level.
"""


def clean_studypack(data: dict, topic: str) -> dict:
    quiz = []
    for q in (data.get("quiz") or [])[:10]:
        opts = _list(q.get("options"), 4, 200)
        idx = q.get("answer_index")
        if len(opts) == 4 and isinstance(idx, int) and 0 <= idx < 4 and _s(q.get("question"), 300):
            quiz.append({"question": _s(q.get("question"), 300), "options": opts, "answer_index": idx,
                         "explanation": _s(q.get("explanation"), 400)})
    bank = []
    for q in (data.get("question_bank") or [])[:12]:
        if _s(q.get("question"), 300):
            bank.append({"question": _s(q.get("question"), 300),
                         "type": q.get("type") if q.get("type") in ("technical", "behavioral", "situational") else "technical",
                         "difficulty": q.get("difficulty") if q.get("difficulty") in ("easy", "medium", "hard") else "medium",
                         "model_answer": _s(q.get("model_answer"), 1200), "key_points": _list(q.get("key_points"), 6, 200)})
    pack = {
        "title": _s(data.get("title"), 120) or topic,
        "topic": topic,
        "notes": [{"heading": _s(n.get("heading"), 120), "body": _s(n.get("body"), 1500)}
                  for n in (data.get("notes") or [])[:8] if _s(n.get("heading"), 120)],
        "definitions": [{"term": _s(d.get("term"), 80), "meaning": _s(d.get("meaning"), 400)}
                        for d in (data.get("definitions") or [])[:12] if _s(d.get("term"), 80)],
        "question_bank": bank, "quiz": quiz,
        "flashcards": [{"front": _s(f.get("front"), 300), "back": _s(f.get("back"), 600)}
                       for f in (data.get("flashcards") or [])[:15] if _s(f.get("front"), 300)],
        "frameworks": [{"name": _s(f.get("name"), 80), "example": _s(f.get("example"), 1200),
                        "steps": [{"name": _s(st.get("name"), 60), "guidance": _s(st.get("guidance"), 400)}
                                  for st in (f.get("steps") or [])[:6] if _s(st.get("name"), 60)]}
                       for f in (data.get("frameworks") or [])[:3] if _s(f.get("name"), 80)],
        "checklist": _list(data.get("checklist"), 10, 200),
    }
    if not (pack["notes"] or pack["question_bank"]):
        raise StudioError("The AI returned an empty study pack. Please try again.")
    return pack


async def make_studypack(api_key: str, topic: str, context: str) -> dict:
    topic = _s(topic, 200)
    if not topic:
        raise StudioError("Please enter a topic.")
    data = await generate(api_key, studypack_prompt(topic, context), StudyPack)
    return clean_studypack(data, topic)


# --- 4. Resume and job description -------------------------------------------

class SkillMatch(BaseModel):
    skill: str
    importance: str = Field(description="required or preferred, as the job description says")
    status: str = Field(description="demonstrated, partial or not_mentioned")
    evidence_quote: str = Field(description="EXACT words copied from the resume that show this skill; empty if none")
    note: str


class TalkingPoint(BaseModel):
    project: str = Field(description="A project or role that IS in the resume")
    how_to_explain: str


class RoadmapStep(BaseModel):
    step: str
    why: str
    related_skill: str


class ResumeMatch(BaseModel):
    role_title: str
    summary: str
    skills: list[SkillMatch]
    technical_questions: list[str]
    behavioral_questions: list[str]
    resume_followups: list[str] = Field(description="Questions an interviewer would ask about things IN the resume")
    talking_points: list[TalkingPoint]
    roadmap: list[RoadmapStep]


def resume_prompt(resume_text: str, job: str) -> str:
    return f"""Compare a candidate's resume with a job description to help them prepare for the interview.

JOB DESCRIPTION:
{job}

RESUME:
{resume_text}

Rules (very important):
- List the skills the job asks for (required and preferred, as written in the job description).
- status 'demonstrated' only if the resume clearly shows it, 'partial' if it shows some of it, otherwise
  'not_mentioned'. 'not_mentioned' means the resume does not say it, NOT that the candidate lacks it.
- evidence_quote must be words copied exactly from the resume. Never invent experience, qualifications,
  achievements or skills.
- talking_points: only projects and roles that are actually in the resume.
- Give 5-8 technical questions, 4-6 behavioural questions and 4-6 follow-up questions about the resume.
- roadmap: 4-7 preparation steps, most important first.
- Never promise the candidate will get the job.
"""


async def make_resume_match(api_key: str, resume_text: str, job: str) -> dict:
    import resume as rs
    data = await generate(api_key, resume_prompt(resume_text, job), ResumeMatch)
    skills = rs.verify_skills(data.get("skills") or [], resume_text)
    if not skills:
        raise StudioError("No skills could be read from the job description. Paste the full job advert and try again.")
    role = _s(data.get("role_title"), 100) or "Target role"
    resume_lower = rs._norm(resume_text)
    talking = []
    for t in (data.get("talking_points") or [])[:6]:
        proj = _s(t.get("project"), 120)
        # only keep projects whose name appears in the resume
        words = [w for w in rs._norm(proj).split() if len(w) > 3]
        if proj and words and sum(w in resume_lower for w in words) >= max(1, len(words) // 2):
            talking.append({"project": proj, "how_to_explain": _s(t.get("how_to_explain"), 600)})
    counts = {st: sum(s["status"] == st for s in skills) for st in rs.STATUSES}
    return {
        "role_title": role, "summary": _s(data.get("summary"), 800), "skills": skills, "counts": counts,
        "questions": {"technical": _list(data.get("technical_questions"), 10),
                      "behavioral": _list(data.get("behavioral_questions"), 8),
                      "resume_followups": _list(data.get("resume_followups"), 8)},
        "talking_points": talking,
        "roadmap": [{"step": _s(r.get("step"), 200), "why": _s(r.get("why"), 300),
                     "related_skill": _s(r.get("related_skill"), 80)}
                    for r in (data.get("roadmap") or [])[:8] if _s(r.get("step"), 200)],
        "diagram": rs.skill_match_diagram(role, skills),
        "caveat": "This comparison is based only on the text of your resume and the job description. "
                  "'Not mentioned' means your resume does not say it, not that you lack the skill. "
                  "It cannot predict whether you will get the job.",
    }


# --- 5. Learning assistant -------------------------------------------------------

class AssistantReply(BaseModel):
    reply: str
    action: str = Field(description="none, diagram, practice or studypack")
    action_topic: str = Field(description="topic for the action, or empty")
    diagram_kind: str = Field(description="mindmap, concept, flowchart, star or empty")


def assistant_prompt(context: str, messages: list[dict]) -> str:
    convo = "\n".join(f"{'USER' if m.get('role') == 'user' else 'ASSISTANT'}: {_s(m.get('text'), 2000)}"
                      for m in messages[-12:])
    return f"""You are a friendly, accurate interview-preparation tutor inside the AI Interview Coach app.
Answer the user's latest message using the context below when relevant.

CONTEXT (the user's own material; it may be empty):
{context or '(none)'}

Guidelines: simple language suited to the user's level; give examples; when the user is practising, offer
a hint before revealing a full answer; when explaining feedback, point to the actual answer and criteria in
the context; say clearly when you are not sure; never invent scores or things the user said.
If the user asks for a mind map, flowchart, concept diagram or answer structure, set action='diagram' with
the topic and diagram_kind (the app will draw it). If they want to practise a topic out loud, set
action='practice'. If they want notes, flashcards or a quiz, set action='studypack'. Otherwise 'none'.
Keep replies under 220 words unless asked for more. No markdown tables.

CONVERSATION:
{convo}
"""


async def assistant(api_key: str, context: str, messages: list[dict]) -> dict:
    data = await generate(api_key, assistant_prompt(context, messages), AssistantReply, models=FAST_MODELS,
                          temperature=0.5)
    action = data.get("action") if data.get("action") in ("none", "diagram", "practice", "studypack") else "none"
    kind = data.get("diagram_kind") if data.get("diagram_kind") in DIAGRAM_KINDS else "mindmap"
    reply = (data.get("reply") or "").strip()[:4000]
    if not reply:
        raise StudioError("The assistant did not answer. Please try again.")
    return {"reply": reply, "action": action, "action_topic": _s(data.get("action_topic"), 120),
            "diagram_kind": kind}


def report_context(session: dict) -> str:
    """Context for the assistant / diagrams from one saved session (only that one)."""
    return digest_reports([session], max_chars=8000)


def material_context(material: dict, node_id: str = "") -> str:
    d = material.get("data") or {}
    kind = material.get("kind")
    if kind == "diagram":
        txt = f"Diagram '{d.get('title')}': " + "; ".join(f"{n['label']}: {n.get('detail', '')}" for n in d.get("nodes", [])[:30])
        if node_id:
            node = next((n for n in d.get("nodes", []) if n["id"] == node_id), None)
            if node:
                txt = f"The user selected the node '{node['label']}': {node.get('detail', '')}\n" + txt
        return txt[:6000]
    return json.dumps(d, ensure_ascii=False)[:6000]
