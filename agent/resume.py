"""
Resume and job-description helpers (no extra packages needed).

- Word (.docx) and text (.txt) resumes are read here with Python's standard
  library. PDF resumes are read in the browser (pdf.js) and arrive as text.
- The AI's skill matches are checked against the actual resume text: a skill
  only counts as "demonstrated" or "partial" if the quoted evidence really is
  in the resume. Otherwise it becomes "not mentioned" (not "missing"): the
  resume may simply not say it.
- The resume text is never written to logs and is not stored; only the
  analysis is saved, and only if the user chooses to save it.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 30_000
MIN_TEXT_CHARS = 80
ALLOWED = {".docx", ".txt"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ResumeError(ValueError):
    """A problem the user can fix (wrong type, too big, empty...)."""


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    ext = name[name.rfind("."):] if "." in name else ""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ResumeError("The file is larger than 5 MB. Please upload a smaller file.")
    if ext not in ALLOWED:
        raise ResumeError("Please upload a .pdf, .docx or .txt file (PDFs are read in your browser).")
    if ext == ".docx":
        text = _docx_text(data)
    else:
        text = _txt(data)
    return clean_text(text)


def _txt(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                raise ResumeError("This .docx file has no document text inside.")
            info = z.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:
                raise ResumeError("This .docx file is too large to read.")
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except zipfile.BadZipFile:
        raise ResumeError("This file is not a valid .docx document.") from None
    except ElementTree.ParseError:
        raise ResumeError("The .docx document could not be read.") from None
    paragraphs = []
    for p in root.iter(W + "p"):
        parts = []
        for node in p.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_TEXT_CHARS]


def validate_inputs(resume_text: str, job_description: str) -> tuple[str, str]:
    resume_text, job_description = clean_text(resume_text), clean_text(job_description)
    if len(resume_text) < MIN_TEXT_CHARS:
        raise ResumeError("The resume text is too short. Upload your resume or paste more of it.")
    if len(job_description) < MIN_TEXT_CHARS:
        raise ResumeError("The job description is too short. Paste the full job advert.")
    return resume_text, job_description[:15_000]


# --- evidence check -----------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", (s or "").lower()).strip()


def evidence_found(quote: str, resume_text: str) -> bool:
    """True if the quoted evidence really appears in the resume (allowing small
    differences in punctuation, case and spacing)."""
    q, r = _norm(quote), _norm(resume_text)
    if len(q) < 3:
        return False
    if q in r:
        return True
    words = q.split()
    if len(words) < 3:
        return False
    # a long quote: accept if a run of at least 80% of its words appears in order
    need = max(3, int(len(words) * 0.8 + 0.5))
    for start in range(0, len(words) - need + 1):
        if " ".join(words[start:start + need]) in r:
            return True
    return False


STATUSES = ("demonstrated", "partial", "not_mentioned")


def verify_skills(skills: list[dict], resume_text: str) -> list[dict]:
    out = []
    for s in skills or []:
        skill = str(s.get("skill", "")).strip()[:80]
        if not skill:
            continue
        status = s.get("status") if s.get("status") in STATUSES else "not_mentioned"
        quote = str(s.get("evidence_quote", "")).strip()[:400]
        note = str(s.get("note", "")).strip()[:400]
        verified = False
        if status in ("demonstrated", "partial"):
            if evidence_found(quote, resume_text):
                verified = True
            else:
                status = "not_mentioned"
                note = ("The AI suggested evidence for this skill, but that text could not be found in your "
                        "resume, so it is shown as not mentioned. " + note).strip()
                quote = ""
        else:
            quote = ""
        importance = s.get("importance") if s.get("importance") in ("required", "preferred") else "required"
        out.append({"skill": skill, "importance": importance, "status": status,
                    "evidence_quote": quote, "evidence_verified": verified, "note": note})
    # one entry per skill name
    seen, unique = set(), []
    for s in out:
        k = s["skill"].lower()
        if k not in seen:
            seen.add(k)
            unique.append(s)
    return unique[:40]


def skill_match_diagram(role: str, skills: list[dict]) -> dict:
    """Built directly from the verified skills (no AI), so it always matches the report."""
    label = {"demonstrated": "Shown in resume", "partial": "Partly shown", "not_mentioned": "Not mentioned"}
    role_ids = {"demonstrated": "strength", "partial": "improve", "not_mentioned": "unassessed"}
    nodes = [{"id": "role", "label": (role or "Target role")[:70], "role": "role",
              "detail": "Skills the job description asks for, grouped by what your resume shows."}]
    edges = []
    for status in STATUSES:
        items = [s for s in skills if s["status"] == status]
        if not items:
            continue
        gid = f"group-{status}"
        nodes.append({"id": gid, "label": f"{label[status]} ({len(items)})", "role": "group",
                      "detail": {"demonstrated": "Your resume gives evidence for these.",
                                 "partial": "Your resume touches on these, but the evidence is thin.",
                                 "not_mentioned": "Your resume does not mention these. That does not mean you "
                                                  "lack them: add evidence if you have it, or prepare to "
                                                  "talk about them."}[status]})
        edges.append({"source": "role", "target": gid, "label": ""})
        for i, s in enumerate(items):
            nid = f"{status}-{i}"
            detail = s["note"] or ""
            if s["evidence_quote"]:
                detail = f'Evidence from your resume: "{s["evidence_quote"]}". ' + detail
            nodes.append({"id": nid, "label": s["skill"], "role": role_ids[status],
                          "detail": detail.strip() or label[status],
                          "evidence": s["evidence_quote"], "importance": s["importance"]})
            edges.append({"source": gid, "target": nid, "label": s["importance"]})
    return {"kind": "skillgap", "title": f"Skill match: {role or 'target role'}",
            "summary": "Built from the verified comparison of your resume with the job description.",
            "nodes": nodes, "edges": edges}
