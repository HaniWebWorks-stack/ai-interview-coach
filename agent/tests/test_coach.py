"""Automated tests for the parts of the coach that don't need any AI service.
Run with run-tests.bat (or: python -m unittest discover -s agent/tests)."""

import pathlib
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import coach_logic as cl  # noqa: E402
import evaluation  # noqa: E402
import storage  # noqa: E402


class ReadyCheckRule(unittest.TestCase):
    def setUp(self):
        self.st = cl.CoachState()
        p = self.st.profile
        p.interview_type, p.role, p.experience_level = "Python job", "Developer", "junior"

    def test_needs_profile_first(self):
        st = cl.CoachState()
        self.assertFalse(st.can_start_interview(cl.READY_QUESTION, True)[0])

    def test_needs_ready_question(self):
        self.assertFalse(self.st.can_start_interview("Good answer!", True)[0])

    def test_needs_user_answer(self):
        self.assertFalse(self.st.can_start_interview(cl.READY_QUESTION, False)[0])

    def test_allowed_after_question_and_answer(self):
        self.assertTrue(self.st.can_start_interview(cl.READY_QUESTION, True)[0])

    def test_not_twice(self):
        self.st.phase = cl.INTERVIEW
        self.assertFalse(self.st.can_start_interview(cl.READY_QUESTION, True)[0])


class Timer(unittest.TestCase):
    def test_pause_keeps_time(self):
        t = cl.InterviewTimer(duration=5)
        t.start(); time.sleep(0.2); t.pause()
        before = t.elapsed
        time.sleep(0.2)
        self.assertAlmostEqual(before, t.elapsed, places=2)
        self.assertFalse(t.running)

    def test_resume_continues(self):
        t = cl.InterviewTimer(duration=5)
        t.start(); time.sleep(0.1); t.pause(); t.start(); time.sleep(0.1)
        self.assertGreater(t.elapsed, 0.15)
        self.assertLess(t.remaining, 5)


class Categories(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(cl.categorize("Python developer interview"), "technical")
        self.assertEqual(cl.categorize("University admission"), "academic")
        self.assertEqual(cl.categorize("Scholarship interview"), "academic")
        self.assertEqual(cl.categorize("Sales manager"), "business")
        self.assertEqual(cl.categorize("Internship at a bank"), "internship")
        self.assertEqual(cl.categorize("Airline pilot"), "general")

    def test_each_category_has_its_own_rubric(self):
        names = {c: tuple(evaluation.RUBRICS[c]["criteria"]) for c in evaluation.RUBRICS}
        self.assertNotEqual(names["technical"], names["academic"])


class Instructions(unittest.TestCase):
    def test_interviewer_rules_have_no_hints_rule(self):
        self.assertIn("Do NOT give hints", cl.guidance_interview_started())

    def test_prompt_contains_exact_ready_question(self):
        self.assertIn(cl.READY_QUESTION, cl.system_instructions(cl.CoachState(), "English"))

    def test_recap_added_after_reconnect(self):
        text = cl.system_instructions(cl.CoachState(), "English", recap="User: hello")
        self.assertIn("User: hello", text)

    def test_final_question_warning(self):
        self.assertIn("final question", cl.guidance_after_question(80))
        self.assertNotIn("final question", cl.guidance_after_question(400))


class Reports(unittest.TestCase):
    def test_scores_clamped(self):
        r = evaluation.clean_report({"overall_score": 140, "criteria": [{"score": 9}],
                                     "questions": [{"relevance": -1, "correctness": 7, "clarity_structure": 3, "completeness": 5}]})
        self.assertEqual(r["overall_score"], 100)
        self.assertEqual(r["criteria"][0]["score"], 5)
        self.assertEqual(r["questions"][0]["relevance"], 0)

    def test_hindi_script_detected(self):
        self.assertTrue(evaluation.needs_script_fix("नो वेट"))
        self.assertFalse(evaluation.needs_script_fix("No wait"))


class QuestionLog(unittest.TestCase):
    T = [
        {"role": "assistant", "phase": "discovery", "text": "What kind of interview are you preparing for?"},
        {"role": "user", "phase": "discovery", "text": "Python developer."},
        {"role": "assistant", "phase": "preparation",
         "text": "Great. Imagine a list has a million items in it. How would you find duplicates?"},
        {"role": "user", "phase": "preparation", "text": "I would use a set."},
        {"role": "assistant", "phase": "preparation", "text": "Good, a set is fast. Also mention memory. Does that make sense?"},
        {"role": "assistant", "phase": "preparation", "text": cl.READY_QUESTION},
        {"role": "user", "phase": "ready_check", "text": "Yes, start."},
        {"role": "assistant", "phase": "interview",
         "text": "Hello, I am your interviewer. Tell me about a time you handled a difficult customer?"},
        {"role": "user", "phase": "interview", "text": "I fixed a delivery problem."},
    ]

    def test_practice_and_interview_questions(self):
        log = cl.build_question_log(self.T)
        self.assertEqual([q["phase"] for q in log], ["practice", "interview"])
        self.assertEqual(log[0]["question"],
                         "Imagine a list has a million items in it. How would you find duplicates?")
        self.assertEqual(log[0]["answer"], "I would use a set.")
        self.assertTrue(log[0]["feedback"].startswith("Good, a set is fast"))
        # greeting not glued to the question; no feedback in the interview itself
        self.assertEqual(log[1]["question"], "Tell me about a time you handled a difficult customer?")
        self.assertEqual(log[1]["feedback"], "")

    def test_report_feedback_attached_to_interview_question(self):
        rq = [{"question": "Describe a time you handled a difficult customer.", "improved_answer": "Use STAR.",
               "improvements": ["Give a result"], "answer_summary": "Fixed delivery."}]
        out = cl.attach_feedback(cl.build_question_log(self.T), rq)
        self.assertEqual(out[1]["improved_answer"], "Use STAR.")
        self.assertNotIn("improved_answer", out[0])  # practice question untouched

    def test_old_saves_without_question_log(self):
        qs = cl.session_questions({"questions": []}, self.T)
        self.assertEqual(len(qs), 2)

    def test_small_talk_and_ready_question_skipped(self):
        log = cl.build_question_log(self.T)
        self.assertFalse(any("make sense" in q["question"] or "mock interview" in q["question"] for q in log))
        extra = [{"role": "assistant", "phase": "preparation",
                  "text": "Be brief and positive, and finish with what you learned. Ready for the next one?"}]
        self.assertEqual(cl.build_question_log(extra), [])


class TargetedPractice(unittest.TestCase):
    def test_focus_skips_discovery_and_is_in_instructions(self):
        st = cl.CoachState()
        st.apply_focus({"topic": "Python decorators", "kind": "reassess", "questions": ["What does @wraps do?"],
                        "interview_type": "Technical interview", "role": "Backend developer", "level": "junior"})
        self.assertEqual(st.phase, cl.PREPARATION)
        self.assertEqual(st.profile.category, "technical")
        text = cl.system_instructions(st, "English")
        self.assertIn("TARGETED PRACTICE SESSION", text)
        self.assertIn("What does @wraps do?", text)
        self.assertIn("REASSESSMENT", text)
        self.assertIn("Python decorators", cl.greeting_for(st))
        ok, _ = st.can_start_interview(cl.READY_QUESTION, True)
        self.assertTrue(ok)

    def test_normal_session_unchanged(self):
        st = cl.CoachState()
        self.assertEqual(cl.greeting_for(st), cl.GREETING)
        self.assertNotIn("TARGETED", cl.system_instructions(st, "English"))


class ReadyButton(unittest.TestCase):
    def test_button_start_does_not_ask_ready_question_again(self):
        self.assertNotIn(cl.READY_QUESTION, cl.START_FROM_BUTTON)
        self.assertIn("do not ask whether they are ready", cl.START_FROM_BUTTON)
        self.assertIn("ask the first question", cl.START_FROM_BUTTON)


class WorksheetCleaning(unittest.TestCase):
    def test_one_item_per_question_and_known_verdicts(self):
        out = evaluation.clean_worksheet([{"verdict": "Needs work", "model_answer": "x", "key_points": ["a", ""]}], 2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["verdict"], "needs_work")
        self.assertEqual(out[0]["key_points"], ["a"])
        self.assertEqual(out[1]["verdict"], "partly")  # missing item padded

    def test_prompt_lists_every_question(self):
        p = evaluation.worksheet_prompt({"interview_type": "HR"}, [{"phase": "practice", "question": "Q one?", "answer": ""}])
        self.assertIn("Q1 (practice): Q one?", p)
        self.assertIn("exactly 1 items", p)


class History(unittest.TestCase):
    def test_update_report(self):
        db = pathlib.Path(tempfile.mkdtemp()) / "t.db"
        storage.save_session("b1", {}, "hr", 1, "x", {"kind": "practice"}, [], path=db)
        storage.update_report("b1", {"kind": "practice", "worksheet": [1]}, path=db)
        self.assertEqual(storage.get_session("b1", db)["report"]["worksheet"], [1])

    def test_save_list_delete(self):
        db = pathlib.Path(tempfile.mkdtemp()) / "t.db"
        storage.save_session("a1", {"interview_type": "HR"}, "hr", 10, "time", {"overall_score": 70}, [], path=db)
        self.assertEqual([s["id"] for s in storage.list_sessions(db)], ["a1"])
        self.assertEqual(storage.get_session("a1", db)["report"]["overall_score"], 70)
        self.assertTrue(storage.delete_session("a1", db))
        self.assertEqual(storage.list_sessions(db), [])


if __name__ == "__main__":
    unittest.main()
