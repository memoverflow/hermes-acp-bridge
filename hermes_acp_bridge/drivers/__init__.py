"""Driver factory."""

from .base import BaseDriver
from .claude import ClaudeDriver
from .codex import CodexDriver
from typing import Optional


def create_driver(cli: str, cwd: str = ".", model: Optional[str] = None, effort: Optional[str] = None, resume_id: Optional[str] = None) -> BaseDriver:
    """Create a driver for the specified CLI."""
    if cli == "claude":
        return ClaudeDriver(cwd=cwd, model=model, effort=effort, resume_id=resume_id)
    elif cli == "codex":
        return CodexDriver(cwd=cwd, model=model, effort=effort, resume_id=resume_id)
    else:
        raise ValueError(f"Unsupported CLI: {cli}. Use 'claude' or 'codex'.")
