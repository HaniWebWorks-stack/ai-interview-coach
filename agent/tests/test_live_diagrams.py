"""The live coach can put diagrams on screen while she explains (coach.diagram)."""
import asyncio
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import agent  # noqa: E402
import coach_logic as cl  # noqa: E402
import storage  # noqa: E402
import studio  # noqa: E402

GOOD = {"title": "Python data structures", "summary": "Overview",
        "nodes": [{"id": "r", "label": "Data structures", "detail": "d", "role": "root"},
                  {"id": "a", "label": "Lists", "detail": "ordered", "role": "branch"},
                  {"id": "b", "label": "Dicts", "detail": "key value", "role": "branch"}],
        "edges": [{"source": "r", "target": "a"}, {"source": "r", "target": "b"}]}


class FakeParticipant:
    def __init__(self):
        self.sent = []

    async def send_text(self, text, topic, compress=False):
        self.sent.append((topic, json.loads(text)))


def make_ctl():
    part = FakeParticipant()
    ctx = SimpleNamespace(room=SimpleNamespace(local_participant=part))
    log = SimpleNamespace(write=lambda m: None)
    ctl = agent.SessionController(ctx, log)
    ctl.state.phase = cl.PREPARATION
    ctl.state.profile.interview_type = "Python developer job"
    return ctl, part


class LiveDiagramTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.tmp.name) / "t.db"
        self._p = mock.patch.object(storage, "DB_PATH", self.db)
        self._p.start()
        storage.save_material.__defaults__ = (self.db,)  # default path argument

    async def asyncTearDown(self):
        self._p.stop()
        storage.save_material.__defaults__ = (storage.DB_PATH,)
        self.tmp.cleanup()

    async def _wait(self, ctl):
        for _ in range(50):
            if not [t for t in ctl.bg if "keep_talking" not in repr(t.get_coro())]:
                break
            await asyncio.sleep(0.01)
        for t in list(ctl.bg):  # no voice session in these tests
            t.cancel()

    async def test_pending_then_ready_with_cleaned_diagram(self):
        ctl, part = make_ctl()
        prompts = []

        async def fake_generate(key, prompt, schema, models=None, temperature=0.3):
            prompts.append((prompt, models))
            return GOOD
        with mock.patch.object(studio, "generate", fake_generate):
            msg = await ctl.show_diagram("Python data structures", "mindmap")
            await self._wait(ctl)
        self.assertEqual(msg, cl.AFTER_VISUAL)
        self.assertIn("Carry on talking", msg)
        topics = [t for t, _ in part.sent]
        self.assertEqual(topics, ["coach.diagram", "coach.diagram"])
        self.assertEqual(part.sent[0][1]["status"], "pending")
        ready = part.sent[1][1]
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["diagram"]["kind"], "mindmap")
        self.assertEqual(ready["diagram"]["nodes"][0]["role"], "root")
        self.assertFalse(ready["saved"])  # not saved unless the user ticked "save"
        self.assertIn("Python developer job", prompts[0][0])  # uses the session profile
        self.assertEqual(prompts[0][1], studio.FAST_MODELS)  # fast models for live use

    async def test_saved_to_studio_when_history_on(self):
        ctl, part = make_ctl()
        ctl.save_history = True

        async def fake_generate(*a, **k):
            return GOOD
        with mock.patch.object(studio, "generate", fake_generate):
            await ctl.show_diagram("Python data structures", "mindmap")
            await self._wait(ctl)
        ready = part.sent[-1][1]
        self.assertTrue(ready["saved"])
        m = storage.get_material(ready["id"], path=self.db)
        self.assertEqual(m["kind"], "diagram")

    async def test_not_during_interview_and_no_duplicates(self):
        ctl, part = make_ctl()

        async def fake_generate(*a, **k):
            return GOOD
        with mock.patch.object(studio, "generate", fake_generate):
            ctl.state.phase = cl.INTERVIEW
            msg = await ctl.show_diagram("Python", "mindmap")
            self.assertIn("not shown during", msg)
            self.assertEqual(part.sent, [])
            ctl.state.phase = cl.PREPARATION
            await ctl.show_diagram("Python", "weird-kind")  # unknown type falls back to mind map
            await self._wait(ctl)
            again = await ctl.show_diagram("python", "mindmap")
        self.assertIn("already on the user's screen", again)
        self.assertEqual(part.sent[0][1]["kind"], "mindmap")

    async def test_failure_reported_honestly_and_retry_allowed(self):
        ctl, part = make_ctl()

        async def failing(*a, **k):
            raise studio.StudioError("Google's free limit was reached. Please wait a minute.")
        with mock.patch.object(studio, "generate", failing):
            await ctl.show_diagram("SQL joins", "flowchart")
            await self._wait(ctl)
        err = part.sent[-1][1]
        self.assertEqual(err["status"], "error")
        self.assertIn("free limit", err["error"])
        self.assertEqual(ctl.diagram_jobs, 0)
        self.assertNotIn("flowchart:sql joins", ctl.diagram_topics)

    async def test_coach_reminded_to_continue_if_quiet_after_diagram(self):
        ctl, part = make_ctl()
        replies = []
        ctl.session = SimpleNamespace(agent_state="listening", user_state="listening",
                                      generate_reply=lambda instructions: replies.append(instructions))
        ctl.VISUAL_SILENCE = 0.3
        await ctl.keep_talking_after_visual()
        self.assertEqual(replies, [cl.CONTINUE_AFTER_VISUAL])
        self.assertIsNotNone(ctl.awaiting_reply_since)  # the normal watchdog takes over

    async def test_no_reminder_when_user_talks_or_coach_continues(self):
        ctl, _ = make_ctl()
        replies = []
        sess = SimpleNamespace(agent_state="listening", user_state="speaking",
                               generate_reply=lambda instructions: replies.append(instructions))
        ctl.session = sess
        ctl.VISUAL_SILENCE = 0.3
        await ctl.keep_talking_after_visual()  # the user is talking: leave it alone
        sess.user_state = "listening"

        sess.agent_state = "speaking"  # finishing her sentence first

        async def stops_then_resumes():
            await asyncio.sleep(0.3)
            sess.agent_state = "listening"
            await asyncio.sleep(0.5)  # a short pause, shorter than VISUAL_SILENCE
            sess.agent_state = "speaking"
        ctl.VISUAL_SILENCE = 1.0
        await asyncio.wait_for(asyncio.gather(ctl.keep_talking_after_visual(), stops_then_resumes()), 5)
        self.assertEqual(replies, [])

    def test_instructions_tell_coach_to_teach_visually(self):
        text = cl.system_instructions(cl.CoachState(), "English")
        self.assertIn("show_diagram", text)
        self.assertIn("Never use it during the formal mock interview", text)


if __name__ == "__main__":
    unittest.main()
