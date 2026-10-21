"""
Progress over time, calculated only from saved interview reports (no AI).

Rules:
- Only scored mock interviews count for scores; practice-only sessions count
  as practice activity.
- Interviews are only compared with interviews of the same category
  (technical with technical, HR with HR, ...), because the criteria differ.
- A criterion score of 0 means "not enough evidence" and is left out.
- With fewer than two interviews in a category there is no trend; the result
  says so instead of inventing one.
"""

from __future__ import annotations

import datetime

from evaluation import RUBRICS

WEAK = 2    # a criterion scored 1-2 is weak
STRONG = 4  # 4-5 is strong


def _date(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _week(ts: float) -> str:
    d = datetime.date.fromtimestamp(ts)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def scored(session: dict) -> bool:
    r = session.get("report") or {}
    return r.get("kind", "interview") != "practice" and isinstance(r.get("overall_score"), int) \
        and not r.get("error") and bool(r.get("criteria"))


def analyse(sessions: list[dict], category: str = "", role: str = "") -> dict:
    """sessions: full saved sessions (any order). Returns the progress overview."""
    sessions = sorted(sessions, key=lambda s: s.get("created_at") or 0)
    if role:
        sessions = [s for s in sessions if (s.get("role") or "").strip().lower() == role.strip().lower()]
    interviews = [s for s in sessions if scored(s)]
    categories = sorted({s.get("category") or "general" for s in interviews})
    out_categories = []
    for cat in categories:
        if category and cat != category:
            continue
        items = [s for s in interviews if (s.get("category") or "general") == cat]
        out_categories.append(_category(cat, items))

    activity: dict[str, dict] = {}
    timeline = []
    for s in sessions:
        r = s.get("report") or {}
        week = _week(s["created_at"])
        a = activity.setdefault(week, {"week": week, "interviews": 0, "practice": 0})
        if scored(s):
            a["interviews"] += 1
        else:
            a["practice"] += 1
        timeline.append({
            "id": s["id"], "date": _date(s["created_at"]), "created_at": s["created_at"],
            "kind": "interview" if scored(s) else "practice",
            "title": (s.get("interview_type") or "Session") + (f", {s['role']}" if s.get("role") else ""),
            "category": s.get("category") or "general",
            "score": r.get("overall_score") if scored(s) else None,
            "focus": (r.get("focus") or {}).get("topic", ""),
        })
    return {
        "categories": out_categories,
        "activity": sorted(activity.values(), key=lambda a: a["week"]),
        "timeline": list(reversed(timeline)),
        "totals": {"sessions": len(sessions), "interviews": len(interviews),
                   "practice": len(sessions) - len(interviews)},
        "filters": {
            "categories": [{"id": c, "label": RUBRICS.get(c, RUBRICS["general"])["label"]}
                           for c in sorted({s.get("category") or "general" for s in sessions})],
            "roles": sorted({(s.get("role") or "").strip() for s in sessions if (s.get("role") or "").strip()}),
        },
    }


def _category(cat: str, items: list[dict]) -> dict:
    scores = [{"id": s["id"], "date": _date(s["created_at"]), "created_at": s["created_at"],
               "score": s["report"]["overall_score"], "interview_type": s.get("interview_type") or "",
               "role": s.get("role") or ""} for s in items]
    enough = len(scores) >= 2
    trend = {"enough_data": enough, "count": len(scores)}
    if enough:
        trend.update(first=scores[0]["score"], latest=scores[-1]["score"],
                     change=scores[-1]["score"] - scores[0]["score"],
                     average=round(sum(x["score"] for x in scores) / len(scores), 1))
    elif scores:
        trend.update(latest=scores[-1]["score"])

    # criterion series (same category => same rubric names)
    series: dict[str, list[dict]] = {}
    for s in items:
        for c in s["report"].get("criteria", []):
            if int(c.get("score") or 0) <= 0:
                continue  # not enough evidence in that interview
            series.setdefault(c["name"], []).append(
                {"date": _date(s["created_at"]), "created_at": s["created_at"], "score": int(c["score"]),
                 "session_id": s["id"]})
    latest_id = items[-1]["id"] if items else None
    criteria, repeated_weak, strong, improved, reassess = [], [], [], [], []
    for name, pts in series.items():
        vals = [p["score"] for p in pts]
        entry = {"name": name, "points": pts, "average": round(sum(vals) / len(vals), 2),
                 "latest": vals[-1], "assessed": len(vals)}
        if len(vals) >= 2:
            entry["change"] = vals[-1] - vals[0]
        criteria.append(entry)
        weak_count = sum(v <= WEAK for v in vals)
        if weak_count >= 2:
            repeated_weak.append({"name": name, "times_weak": weak_count, "assessed": len(vals), "latest": vals[-1]})
        if sum(v >= STRONG for v in vals) >= 2 and vals[-1] > WEAK:
            strong.append({"name": name, "average": entry["average"], "assessed": len(vals)})
        if len(vals) >= 2 and vals[-1] - vals[0] >= 1 and vals[-1] >= 3:
            improved.append({"name": name, "from": vals[0], "to": vals[-1]})
        was_weak = any(v <= WEAK for v in vals)
        assessed_latest = pts[-1]["session_id"] == latest_id
        if was_weak and not assessed_latest:
            reassess.append({"name": name, "latest": vals[-1],
                             "reason": "was weak before and has not been assessed since"})
        elif vals[-1] <= WEAK:
            reassess.append({"name": name, "latest": vals[-1], "reason": "still weak in the latest interview"})
    return {
        "category": cat,
        "label": RUBRICS.get(cat, RUBRICS["general"])["label"],
        "sessions": scores,
        "trend": trend,
        "criteria": sorted(criteria, key=lambda c: c["name"]),
        "repeated_weaknesses": sorted(repeated_weak, key=lambda c: -c["times_weak"]),
        "strengths": sorted(strong, key=lambda c: -c["average"]),
        "improved": improved,
        "needs_reassessment": reassess,
    }
