"""Tests for ACP protocol handler."""

import asyncio
import json
import unittest

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from hermes_acp_bridge.acp import ACPHandler, jsonrpc_response, jsonrpc_error


class MockSessionManager:
    def __init__(self):
        self.sessions = {}

    async def create_session(self, session_id, cli, cwd, model=None, effort=None):
        self.sessions[session_id] = {"cli": cli, "cwd": cwd}

    async def load_session(self, session_id):
        return session_id in self.sessions

    async def prompt_session(self, session_id, prompt, send_update):
        await send_update("agent_message_chunk", f"Echo: {prompt}")
        return "end_turn"

    async def cancel_session(self, session_id):
        pass


class TestACPHandler(unittest.TestCase):
    def setUp(self):
        self.sm = MockSessionManager()
        self.handler = ACPHandler(self.sm)

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_initialize(self):
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        result = self._run(self.handler.handle_message(msg))
        parsed = json.loads(result)
        self.assertEqual(parsed["id"], 1)
        self.assertIn("agentCapabilities", parsed["result"])
        self.assertEqual(parsed["result"]["protocolVersion"], 1)

    def test_session_new(self):
        msg = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "session/new",
            "params": {"cli": "claude", "cwd": "/tmp"}
        })
        result = self._run(self.handler.handle_message(msg))
        parsed = json.loads(result)
        self.assertIn("sessionId", parsed["result"])
        self.assertEqual(len(self.sm.sessions), 1)

    def test_unknown_method(self):
        msg = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "foo/bar", "params": {}})
        result = self._run(self.handler.handle_message(msg))
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertEqual(parsed["error"]["code"], -32601)

    def test_invalid_json(self):
        result = self._run(self.handler.handle_message("not json"))
        parsed = json.loads(result)
        self.assertEqual(parsed["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
