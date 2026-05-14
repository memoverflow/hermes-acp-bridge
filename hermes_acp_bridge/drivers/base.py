"""Abstract base driver for CLI agents."""

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional


class BaseDriver(ABC):
    """Base class for CLI agent drivers."""

    def __init__(self, cwd: str = ".", model: Optional[str] = None, effort: Optional[str] = None, resume_id: Optional[str] = None):
        self.cwd = cwd
        self.model = model
        self.effort = effort
        self.resume_id = resume_id
        self._process: Optional[asyncio.subprocess.Process] = None

    @abstractmethod
    async def prompt(self, text: str, send_update: Callable[[str, str], Awaitable[None]]) -> str:
        """Send prompt, stream output via send_update, return stop_reason."""
        ...

    async def cancel(self) -> None:
        """Cancel the running process."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3)
            except asyncio.TimeoutError:
                self._process.kill()
            except ProcessLookupError:
                pass

    @abstractmethod
    def build_command(self, prompt: str) -> list[str]:
        """Build the CLI command to execute."""
        ...
