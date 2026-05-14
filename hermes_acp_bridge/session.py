"""Session management and persistence."""

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

from .drivers import create_driver
from .drivers.base import BaseDriver

logger = logging.getLogger(__name__)


class Session:
    """A single ACP session backed by a CLI driver."""

    def __init__(self, session_id: str, cli: str, cwd: str, model: Optional[str], effort: Optional[str], driver: BaseDriver):
        self.session_id = session_id
        self.cli = cli
        self.cwd = cwd
        self.model = model
        self.effort = effort
        self.driver = driver
        self.created_at = time.time()
        self.last_active = time.time()
        self.message_count = 0
        self.status = "active"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "cli": self.cli,
            "cwd": self.cwd,
            "model": self.model,
            "effort": self.effort,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "message_count": self.message_count,
            "status": self.status,
        }


class SessionManager:
    """Manages all active sessions with persistence."""

    def __init__(self, state_dir: Optional[str] = None):
        self.state_dir = Path(state_dir or os.path.expanduser("~/.hermes-acp-bridge"))
        self.sessions_dir = self.state_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}

    @property
    def active_sessions(self) -> dict[str, Session]:
        return self._sessions

    async def create_session(self, session_id: str, cli: str, cwd: str, model: Optional[str] = None, effort: Optional[str] = None) -> Session:
        driver = create_driver(cli, cwd=cwd, model=model, effort=effort)
        session = Session(session_id, cli, cwd, model, effort, driver)
        self._sessions[session_id] = session
        self._persist(session)
        logger.info(f"Created session {session_id} (cli={cli}, cwd={cwd})")
        return session

    async def load_session(self, session_id: str) -> bool:
        """Load a session from disk."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return False

        data = json.loads(path.read_text())
        cli = data.get("cli", "claude")
        cwd = data.get("cwd", ".")
        model = data.get("model")
        effort = data.get("effort")

        driver = create_driver(cli, cwd=cwd, model=model, effort=effort, resume_id=session_id)
        session = Session(session_id, cli, cwd, model, effort, driver)
        session.created_at = data.get("created_at", time.time())
        session.message_count = data.get("message_count", 0)
        self._sessions[session_id] = session
        logger.info(f"Loaded session {session_id}")
        return True

    async def prompt_session(self, session_id: str, prompt: str, send_update: Callable[[str, str], Awaitable[None]]) -> str:
        """Send a prompt to a session and stream back results."""
        session = self._sessions.get(session_id)
        if not session:
            raise RuntimeError(f"Session not found: {session_id}")

        session.last_active = time.time()
        session.message_count += 1
        session.status = "running"

        try:
            stop_reason = await session.driver.prompt(prompt, send_update)
            session.status = "active"
            self._persist(session)
            return stop_reason
        except asyncio.CancelledError:
            session.status = "cancelled"
            return "cancelled"
        except Exception as e:
            session.status = "error"
            logger.error(f"Session {session_id} error: {e}")
            raise

    async def cancel_session(self, session_id: str) -> None:
        """Cancel a running session."""
        session = self._sessions.get(session_id)
        if session and session.driver:
            await session.driver.cancel()
            session.status = "cancelled"

    def _persist(self, session: Session) -> None:
        """Save session state to disk."""
        path = self.sessions_dir / f"{session.session_id}.json"
        path.write_text(json.dumps(session.to_dict(), indent=2))

    async def cleanup(self) -> None:
        """Stop all sessions."""
        for session in self._sessions.values():
            if session.driver:
                await session.driver.cancel()
        self._sessions.clear()
