"""Tests for session persistence and manager."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from hermes_acp_bridge.session import SessionManager


class FakeDriver:
    def __init__(self, *args, **kwargs):
        self.cancelled = False

    async def prompt(self, text, send_update):
        await send_update("agent_message_chunk", f"Echo: {text}")
        return "end_turn"

    async def cancel(self):
        self.cancelled = True


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mgr = SessionManager(state_dir=self.tmp.name)

        # patch driver factory for this test
        import hermes_acp_bridge.session as session_mod

        self._orig_create = session_mod.create_driver
        session_mod.create_driver = lambda cli, **kw: FakeDriver()
        self.addCleanup(lambda: setattr(session_mod, "create_driver", self._orig_create))

    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_create_and_persist(self):
        session = self._run(
            self.mgr.create_session("s1", "claude", "/tmp", model="opus")
        )
        self.assertEqual(session.session_id, "s1")
        self.assertEqual(session.cli, "claude")
        persisted = Path(self.tmp.name) / "sessions" / "s1.json"
        self.assertTrue(persisted.exists())
        data = json.loads(persisted.read_text())
        self.assertEqual(data["cli"], "claude")
        self.assertEqual(data["model"], "opus")

    def test_load_missing(self):
        loaded = self._run(self.mgr.load_session("does-not-exist"))
        self.assertFalse(loaded)

    def test_load_existing(self):
        self._run(self.mgr.create_session("s2", "codex", "/tmp"))
        # drop from memory, keep on disk
        self.mgr._sessions.clear()
        ok = self._run(self.mgr.load_session("s2"))
        self.assertTrue(ok)
        self.assertIn("s2", self.mgr.active_sessions)
        self.assertEqual(self.mgr.active_sessions["s2"].cli, "codex")

    def test_prompt_increments_and_saves(self):
        async def go():
            await self.mgr.create_session("s3", "claude", "/tmp")
            collected = []

            async def send_update(kind, text):
                collected.append((kind, text))

            reason = await self.mgr.prompt_session("s3", "hello", send_update)
            return reason, collected

        reason, collected = self._run(go())
        self.assertEqual(reason, "end_turn")
        self.assertEqual(collected[0][0], "agent_message_chunk")
        self.assertEqual(self.mgr.active_sessions["s3"].message_count, 1)

    def test_cancel_calls_driver(self):
        async def go():
            s = await self.mgr.create_session("s4", "claude", "/tmp")
            await self.mgr.cancel_session("s4")
            return s.driver.cancelled

        self.assertTrue(self._run(go()))


if __name__ == "__main__":
    unittest.main()
