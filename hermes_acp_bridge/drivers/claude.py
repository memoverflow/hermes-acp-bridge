"""Claude Code CLI driver."""

import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional

from .base import BaseDriver

logger = logging.getLogger(__name__)


class ClaudeDriver(BaseDriver):
    """Driver for Claude Code CLI (claude -p --output-format stream-json)."""

    def build_command(self, prompt: str) -> list[str]:
        cmd = [
            "claude", "-p",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.effort:
            cmd.extend(["--effort", self.effort])
        if self.resume_id:
            cmd.extend(["--resume", self.resume_id])
        cmd.append(prompt)
        return cmd

    async def prompt(self, text: str, send_update: Callable[[str, str], Awaitable[None]]) -> str:
        cmd = self.build_command(text)
        logger.info(f"Claude cmd: {' '.join(cmd[:6])}...")

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )

        stop_reason = "end_turn"

        async for line in self._process.stdout:
            line_text = line.decode("utf-8", errors="replace").strip()
            if not line_text:
                continue

            try:
                event = json.loads(line_text)
            except json.JSONDecodeError:
                # Plain text output
                await send_update("agent_message_chunk", line_text)
                continue

            await self._handle_event(event, send_update)

            # Check for stop reason
            if event.get("type") == "result":
                stop_reason = event.get("stop_reason", "end_turn")

        await self._process.wait()
        return stop_reason

    async def _handle_event(self, event: dict, send_update: Callable[[str, str], Awaitable[None]]) -> None:
        """Parse Claude stream-json events and forward as ACP updates."""
        event_type = event.get("type", "")

        if event_type == "stream_event":
            inner = event.get("event", {})
            delta = inner.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    await send_update("agent_message_chunk", text)
            elif delta_type == "thinking_delta":
                text = delta.get("thinking", "")
                if text:
                    await send_update("agent_thought_chunk", text)

        elif event_type == "content_block_start":
            content = event.get("content_block", {})
            if content.get("type") == "tool_use":
                tool_name = content.get("name", "")
                await send_update("agent_thought_chunk", f"⚙ Using tool: {tool_name}\n")

        elif event_type == "result":
            result_text = event.get("result", "")
            if result_text and not any(
                event.get("subtype") == t for t in ("error_max_turns", "error_budget")
            ):
                # Final result already streamed
                pass
