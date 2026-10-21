"""Tests for the Preparation Studio, progress analytics, resume matching and the API.

The only thing replaced in these tests is the network call to Google Gemini
(studio.generate), because the test machine cannot reach Google. Everything
around it (validation, storage, API, security) runs for real.
"""

import asyncio
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import progress as prog  # noqa: E402
import resume as rs  # noqa: E402
import storage  # noqa: E402
import studio  # noqa: E402


def make_docx(paragraphs):
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def session(sid, days_ago, category, score, criteria, kind="interview", role="Engineer"):
    report = {"overall_score": score, "criteria": [{"name": n, "score": v, "comment": ""} for n, v in criteria.items()]}
    if kind == "practice":
        report = {"kind": "practice", "question_log": [{"phase": "practice", "question": "Q?", "answer": "A"}]}
    return {"id": sid, "created_at": time.time() - days_ago * 86400, "category": category,
            "interview_type": "Technical", "role": role, "report": report, "transcript": []}


class Diagrams(unittest.TestCase):
    def test_repairs_ids_edges_and_roles(self):
        d = studio.clean_diagram("mindmap", {"title": "T", "nodes": [
            {"id": "a", "label": "Python", "role": "branch"}, {"id": "a", "label": "Decorators", "role": "leaf"},
            {"id": "c", "label": "Closures", "role": "weird"}],
            "edges": [{"source": "a", "target": "zzz"}, {"source": "a", "target": "c"}, {"source": "c", "target": "c"}]})
        ids = [n["id"] for n in d["nodes"]]
        self.assertEqual(len(set(ids)), 3)                 # duplicate id renamed
        self.assertEqual(d["nodes"][0]["role"], "root")      # a mind map always has a root
        self.assertEqual(d["nodes"][2]["role"], "leaf")      # unknown role -> default
        for e in d["edges"]:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)
            self.assertNotEqual(e["source"], e["target"])
        targets = {e["target"] for e in d["edges"]}
        self.assertTrue(all(n in targets for n in ids[1:]))  # nothing left floating

    def test_skillgap_without_evidence_is_unassessed_not_weak(self):
        d = studio.clean_diagram("skillgap", {"nodes": [
            {"id": "r", "label": "Data analyst", "role": "role"},
            {"id": "s", "label": "SQL", "role": "improve", "evidence": ""},
            {"id": "p", "label": "Python", "role": "strength", "evidence": "Explained pandas well on 2026-10-12"}],
            "edges": []})
        roles = {n["label"]: n["role"] for n in d["nodes"]}
        self.assertEqual(roles["SQL"], "unassessed")
        self.assertEqual(roles["Python"], "strength")

    def test_invalid_diagram_rejected(self):
        with self.assertRaises(studio.DiagramError):
            studio.clean_diagram("flowchart", {"nodes": [{"id": "x", "label": "Only one"}], "edges": []})
        with self.assertRaises(studio.DiagramError):
            studio.clean_diagram("nonsense", {"nodes": [], "edges": []})

    def test_flowchart_gets_start(self):
        d = studio.clean_diagram("flowchart", {"nodes": [{"id": "1", "label": "Read question", "role": "action"},
                                                         {"id": "2", "label": "Answer", "role": "end"}],
                                               "edges": [{"source": "1", "target": "2"}]})
        self.assertEqual(d["nodes"][0]["role"], "start")


class StudyPackAndInsights(unittest.TestCase):
    def test_quiz_items_with_wrong_answer_index_dropped(self):
        pack = studio.clean_studypack({"notes": [{"heading": "H", "body": "B"}], "quiz": [
            {"question": "ok?", "options": ["a", "b", "c", "d"], "answer_index": 2, "explanation": "e"},
            {"question": "bad?", "options": ["a", "b", "c", "d"], "answer_index": 7},
            {"question": "three?", "options": ["a", "b", "c"], "answer_index": 0}]}, "Topic")
        self.assertEqual([q["question"] for q in pack["quiz"]], ["ok?"])

    def test_empty_pack_is_an_error(self):
        with self.assertRaises(studio.StudioError):
            studio.clean_studypack({"notes": [], "question_bank": []}, "Topic")

    def test_insights_enums_cleaned(self):
        ins = studio.clean_insights({"summary": "s", "weaknesses": [
            {"topic": "Decorators", "kind": "bad", "severity": "huge", "practice_questions": ["q1", "q2"]}],
            "recommendations": [{"title": "Practise", "action": "fly"}],
            "reassessment": [{"topic": "SQL", "status": "maybe"}]})
        w = ins["weaknesses"][0]
        self.assertEqual((w["kind"], w["severity"], w["id"]), ("incomplete_answer", "medium", "w1"))
        self.assertEqual(ins["recommendations"][0]["action"], "practice")
        self.assertEqual(ins["reassessment"][0]["status"], "not_reassessed")

    def test_digest_uses_only_real_saved_data(self):
        s = session("a", 1, "technical", 62, {"Technical correctness": 2})
        s["report"]["areas_to_improve"] = ["Explain decorators"]
        bad = {"id": "b", "created_at": time.time(), "report": {"error": "failed"}}
        text = studio.digest_reports([s, bad])
        self.assertIn("score 62/100", text)
        self.assertIn("Explain decorators", text)
        self.assertNotIn("failed", text)


class Resume(unittest.TestCase):
    RESUME = ("Sales Manager at Tapal Tea, Karachi. Led a team of 25 distributor sales staff. "
              "Grew Korangi territory revenue by 18% in 2025 through retail channel development.")

    def test_docx_and_txt_extraction(self):
        text = rs.extract_text("cv.docx", make_docx(["Hani", "Territory Sales Manager"]))
        self.assertIn("Territory Sales Manager", text)
        self.assertEqual(rs.extract_text("cv.txt", "Hello résumé".encode("utf-8")), "Hello résumé")

    def test_bad_files_rejected(self):
        with self.assertRaises(rs.ResumeError):
            rs.extract_text("cv.exe", b"x")
        with self.assertRaises(rs.ResumeError):
            rs.extract_text("cv.docx", b"not a zip")
        with self.assertRaises(rs.ResumeError):
            rs.extract_text("cv.txt", b"x" * (rs.MAX_UPLOAD_BYTES + 1))

    def test_evidence_must_be_in_resume(self):
        out = rs.verify_skills([
            {"skill": "Team leadership", "status": "demonstrated", "evidence_quote": "Led a team of 25 distributor sales staff"},
            {"skill": "SAP", "status": "demonstrated", "evidence_quote": "Expert in SAP S/4HANA"},
            {"skill": "Retail", "status": "partial", "evidence_quote": "retail channel development"},
            {"skill": "Python", "status": "not_mentioned", "evidence_quote": "made up"}], self.RESUME)
        by = {s["skill"]: s for s in out}
        self.assertEqual(by["Team leadership"]["status"], "demonstrated")
        self.assertTrue(by["Team leadership"]["evidence_verified"])
        self.assertEqual(by["SAP"]["status"], "not_mentioned")    # invented evidence is removed
        self.assertIn("could not be found", by["SAP"]["note"])
        self.assertEqual(by["Retail"]["status"], "partial")
        self.assertEqual(by["Python"]["evidence_quote"], "")

    def test_skill_match_diagram_is_valid(self):
        skills = rs.verify_skills([{"skill": "Leadership", "status": "demonstrated",
                                    "evidence_quote": "Led a team of 25"}], self.RESUME)
        d = studio.clean_diagram("skillgap", rs.skill_match_diagram("Sales Manager", skills))
        self.assertEqual({n["role"] for n in d["nodes"]} >= {"role", "group", "strength"}, True)

    def test_inputs_validated(self):
        with self.assertRaises(rs.ResumeError):
            rs.validate_inputs("short", "x" * 200)


class Progress(unittest.TestCase):
    def test_trends_only_within_category_and_no_invented_trend(self):
        data = prog.analyse([
            session("t1", 10, "technical", 50, {"Technical correctness": 2, "Depth of knowledge": 0}),
            session("t2", 5, "technical", 70, {"Technical correctness": 4, "Depth of knowledge": 3}),
            session("h1", 3, "hr", 60, {"Communication": 2}),
            session("p1", 1, "technical", 0, {}, kind="practice")])
        cats = {c["category"]: c for c in data["categories"]}
        self.assertEqual(cats["technical"]["trend"]["change"], 20)
        self.assertFalse(cats["hr"]["trend"]["enough_data"])      # one HR interview: no trend
        depth = next(c for c in cats["technical"]["criteria"] if c["name"] == "Depth of knowledge")
        self.assertEqual(depth["assessed"], 1)                     # score 0 = not enough evidence, ignored
        self.assertEqual(cats["technical"]["improved"][0]["name"], "Technical correctness")
        self.assertEqual(data["totals"], {"sessions": 4, "interviews": 3, "practice": 1})

    def test_repeated_weakness_and_reassessment(self):
        data = prog.analyse([
            session("a", 9, "technical", 40, {"Problem-solving approach": 2, "Technical correctness": 1}),
            session("b", 4, "technical", 45, {"Problem-solving approach": 1}),
        ])
        c = data["categories"][0]
        self.assertEqual(c["repeated_weaknesses"][0]["name"], "Problem-solving approach")
        reasons = {r["name"]: r["reason"] for r in c["needs_reassessment"]}
        self.assertIn("not been assessed since", reasons["Technical correctness"])

    def test_empty_history(self):
        data = prog.analyse([])
        self.assertEqual(data["categories"], [])
        self.assertEqual(data["totals"]["sessions"], 0)


class StorageMigration(unittest.TestCase):
    def test_old_database_keeps_its_reports(self):
        db = pathlib.Path(tempfile.mkdtemp()) / "old.db"
        old = sqlite3.connect(db)
        old.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at REAL NOT NULL, interview_type TEXT, "
                    "role TEXT, experience_level TEXT, category TEXT, minutes REAL, end_reason TEXT, "
                    "overall_score INTEGER, report_json TEXT, transcript_json TEXT)")
        old.execute("INSERT INTO sessions VALUES ('old1', 1, 'HR', 'Manager', 'senior', 'hr', 5, 'x', 70, '{\"overall_score\": 70}', '[]')")
        old.commit()
        old.close()
        self.assertEqual(storage.get_session("old1", db)["report"]["overall_score"], 70)
        storage.save_material("m1", "diagram", "D", {"topic": "t"}, {"nodes": []}, path=db)
        storage.set_progress("roadmap:m1:n1", "done", path=db)
        self.assertEqual(storage.get_progress("roadmap:m1:", db)["roadmap:m1:n1"]["status"], "done")
        self.assertTrue(storage.delete_material("m1", db))
        self.assertEqual(storage.get_progress("roadmap:m1:", db), {})
        self.assertEqual(len(storage.list_sessions(db)), 1)


class Api(unittest.TestCase):
    """Real aiohttp app and handlers; only Gemini's network call is replaced."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()) / "api.db"
        storage.DB_PATH = self.tmp
        for fn in ("save_session", "list_sessions", "get_session", "save_material", "get_material", "list_materials",
                   "update_material_data", "delete_material", "set_progress", "get_progress", "list_full_sessions"):
            f = getattr(storage, fn)
            if f.__defaults__ and isinstance(f.__defaults__[-1], pathlib.Path):
                f.__defaults__ = f.__defaults__[:-1] + (self.tmp,)

    def run_app(self, coro_fn):
        from aiohttp.test_utils import TestClient, TestServer
        import viewer_server

        async def main():
            app = viewer_server.make_app()
            app.cleanup_ctx.clear()
            server = TestServer(app)  # any free port
            async with TestClient(server) as client:
                old = viewer_server.ALLOWED_HOSTS
                viewer_server.ALLOWED_HOSTS = {f"127.0.0.1:{server.port}", f"localhost:{server.port}"}
                try:
                    await coro_fn(client)
                finally:
                    viewer_server.ALLOWED_HOSTS = old
        asyncio.run(main())

    def test_security_and_validation(self):
        async def checks(c):
            r = await c.get("/api/progress", headers={"Host": "evil.example:8765"})
            self.assertEqual(r.status, 403)
            r = await c.post("/api/diagrams", json={"kind": "mindmap", "topic": "x"},
                             headers={"Origin": "https://evil.example"})
            self.assertEqual(r.status, 403)
            r = await c.post("/api/diagrams", json={"kind": "nope", "topic": "x"})
            self.assertEqual(r.status, 400)
            r = await c.post("/api/insights", json={})
            self.assertEqual(r.status, 404)                       # no saved sessions: honest message
            r = await c.get("/api/progress")
            self.assertEqual((await r.json())["totals"]["sessions"], 0)
        self.run_app(checks)

    def test_diagram_flow_with_stand_in_ai(self):
        async def fake_generate(api_key, prompt, schema, models=None, temperature=0.3):
            return {"title": "Decorators", "summary": "s", "nodes": [
                {"id": "r", "label": "Decorators", "detail": "d", "role": "root"},
                {"id": "b", "label": "Closures", "detail": "d", "role": "branch"}],
                "edges": [{"source": "r", "target": "b"}]}
        orig = studio.generate
        studio.generate = fake_generate

        async def flow(c):
            r = await c.post("/api/diagrams", json={"kind": "mindmap", "topic": "Python decorators"})
            self.assertEqual(r.status, 200)
            mid = (await r.json())["material"]["id"]
            r = await c.patch(f"/api/materials/{mid}", json={"node_id": "b", "label": "Closures & scope", "note": "revise"})
            self.assertEqual((await r.json())["node"]["label"], "Closures & scope")
            r = await c.get(f"/api/materials/{mid}")
            self.assertEqual((await r.json())["material"]["data"]["nodes"][1]["note"], "revise")
            r = await c.delete(f"/api/materials/{mid}")
            self.assertTrue((await r.json())["deleted"])
        try:
            self.run_app(flow)
        finally:
            studio.generate = orig

    def test_no_api_key_gives_honest_error(self):
        import os
        old = os.environ.pop("GOOGLE_API_KEY", None)

        async def flow(c):
            r = await c.post("/api/diagrams", json={"kind": "mindmap", "topic": "SQL joins"})
            self.assertEqual(r.status, 502)
            self.assertIn("No Google API key", (await r.json())["error"])
        try:
            self.run_app(flow)
        finally:
            if old is not None:
                os.environ["GOOGLE_API_KEY"] = old

    def test_resume_upload_and_focus(self):
        import studio_api

        async def flow(c):
            from aiohttp import FormData
            fd = FormData()
            fd.add_field("file", make_docx(["Experienced sales manager with 14 years in FMCG distribution "
                                            "and retail channel development across Karachi."]),
                         filename="cv.docx")
            r = await c.post("/api/resume/extract", data=fd)
            self.assertEqual(r.status, 200)
            self.assertIn("FMCG", (await r.json())["text"])
            fd = FormData()
            fd.add_field("file", b"MZ...", filename="cv.exe")
            r = await c.post("/api/resume/extract", data=fd)
            self.assertEqual(r.status, 400)
        self.run_app(flow)
        self.assertIsNone(studio_api.clean_focus({"topic": "  "}))
        f = studio_api.clean_focus({"topic": "Decorators", "kind": "hack", "questions": ["a"] * 9})
        self.assertEqual((f["kind"], len(f["questions"])), ("studio", 5))


if __name__ == "__main__":
    unittest.main()
