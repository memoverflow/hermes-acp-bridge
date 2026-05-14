"""Codex CLI driver."""

import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional

from .base import BaseDriver

logger = logging.getLogger(__name__)


class CodexDriver(BaseDriver):
    """Driver for OpenAI Codex CLI (codex exec)."""

    def build_command(self, prompt: str) -> list[str]:
        cmd = [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if self.model:
            cmd.extend(["-m", self.model])
        if self.effort:
            cmd.extend(["-c", f"model_reasoning_effort={self.effort}"])
        cmd.append(prompt)
        return cmd

    async def prompt(self, text: str, send_update: Callable[[str, str], Awaitable[None]]) -> str:
        cmd = self.build_command(text)
        logger.info(f"Codex cmd: {' '.join(cmd[:5])}...")

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )

        stop_reason = "end_turn"
        buffer = ""

        async for line in self._process.stdout:
            line_text = line.decode("utf-8", errors="replace").strip()
            if not line_text:
                continue

            try:
                event = json.loads(line_text)
                await self._handle_event(event, send_update)
            except json.JSONDecodeError:
                # Plain text output from codex
                await send_update("agent_message_chunk", line_text + "\n")

        await self._process.wait()
        return stop_reason

    async def _handle_event(self, event: dict, send_update: Callable[[str, str], Awaitable[None]]) -> None:
        """Parse Codex JSON events and forward as ACP updates."""
        event_type = event.get("type", "")

        if event_type == "agent_message":
            content = event.get("content", "")
            if content:
                await send_update("agent_message_chunk", content)

        elif event_type == "reasoning":
            content = event.get("content", "")
            if content:
                await send_update("agent_thought_chunk", content)

        elif event_type == "tool_call":
            name = event.get("name", "unknown")
            await send_update("agent_thought_chunk", f"⚙ Tool: {name}\n")

        elif event_type == "command_executed":
            cmd = event.get("command", "")
            exit_code = event.get("exit_code", "")
            await send_update("agent_thought_chunk", f"$ {cmd} (exit: {exit_code})\n")

        elif event_type == "file_written":
            path = event.get("path", "")
            await send_update("agent_thought_chunk", f"📝 Wrote: {path}\n")
