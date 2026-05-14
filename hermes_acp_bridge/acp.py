"""ACP JSON-RPC 2.0 protocol handler."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

_MAX_FS_BYTES = 5 * 1024 * 1024

logger = logging.getLogger(__name__)


class ACPError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def jsonrpc_response(request_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def jsonrpc_error(request_id: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def jsonrpc_notification(method: str, params: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": params})


class ACPHandler:
    """Handles ACP JSON-RPC messages for a single WebSocket connection."""

    def __init__(self, session_manager):
        self.session_manager = session_manager
        self._session_id: Optional[str] = None

    async def handle_message(self, raw: str) -> Optional[str]:
        """Process incoming JSON-RPC message. Returns response string or None for notifications."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return jsonrpc_error(None, -32700, "Parse error")

        method = msg.get("method")
        params = msg.get("params") or {}
        request_id = msg.get("id")

        # Notification (no id) — don't respond
        if request_id is None and method:
            await self._handle_notification(method, params)
            return None

        if not method:
            return jsonrpc_error(request_id, -32600, "Invalid Request: missing method")

        try:
            result = await self._dispatch(method, params)
            return jsonrpc_response(request_id, result)
        except ACPError as e:
            return jsonrpc_error(request_id, e.code, e.message)
        except Exception as e:
            logger.exception(f"Error handling {method}")
            return jsonrpc_error(request_id, -32603, f"Internal error: {e}")

    async def _dispatch(self, method: str, params: dict) -> Any:
        handlers = {
            "initialize": self._handle_initialize,
            "session/new": self._handle_session_new,
            "session/load": self._handle_session_load,
            "session/prompt": self._handle_session_prompt,
            "session/cancel": self._handle_session_cancel,
            "fs/read_text_file": self._handle_fs_read,
            "fs/write_text_file": self._handle_fs_write,
            "session/request_permission": self._handle_permission,
        }
        handler = handlers.get(method)
        if handler is None:
            raise ACPError(-32601, f"Method not found: {method}")
        return await handler(params)

    async def _handle_session_cancel(self, params: dict) -> dict:
        session_id = params.get("sessionId") or self._session_id
        if session_id:
            await self.session_manager.cancel_session(session_id)
        return {"ok": True}

    async def _handle_fs_read(self, params: dict) -> dict:
        path_str = params.get("path")
        if not isinstance(path_str, str) or not path_str:
            raise ACPError(-32602, "path required")
        p = Path(path_str).expanduser()
        if not p.exists() or not p.is_file():
            raise ACPError(-32000, f"file not found: {p}")
        if p.stat().st_size > _MAX_FS_BYTES:
            raise ACPError(-32000, "file too large")
        return {"content": p.read_text(encoding="utf-8", errors="replace")}

    async def _handle_fs_write(self, params: dict) -> dict:
        path_str = params.get("path")
        if not isinstance(path_str, str) or not path_str:
            raise ACPError(-32602, "path required")
        content = params.get("content", "")
        if not isinstance(content, str):
            raise ACPError(-32602, "content must be string")
        data = content.encode("utf-8")
        if len(data) > _MAX_FS_BYTES:
            raise ACPError(-32000, "content too large")
        p = Path(path_str).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "bytes": len(data)}

    async def _handle_permission(self, params: dict) -> dict:
        options = params.get("options") or []
        chosen: Optional[dict] = None
        for opt in options:
            if not isinstance(opt, dict):
                continue
            kind = str(opt.get("kind", "")).lower()
            option_id = str(opt.get("optionId", "")).lower()
            if kind.startswith("allow") or "allow" in option_id:
                chosen = opt
                break
        if chosen is None and options and isinstance(options[0], dict):
            chosen = options[0]
        return {
            "outcome": {
                "outcome": "selected",
                "optionId": (chosen or {}).get("optionId", "allow"),
            }
        }

    async def _handle_notification(self, method: str, params: dict) -> None:
        if method == "session/cancel":
            session_id = params.get("sessionId") or self._session_id
            if session_id:
                await self.session_manager.cancel_session(session_id)

    async def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": 1,
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": True,
                },
            },
            "agentInfo": {
                "name": "hermes-acp-bridge",
                "title": "Hermes ACP Bridge",
                "version": "0.1.0",
            },
        }

    async def _handle_session_new(self, params: dict) -> dict:
        cli = params.get("cli", "claude")
        cwd = params.get("cwd", ".")
        model = params.get("model")
        effort = params.get("effort")

        session_id = str(uuid.uuid4())
        self._session_id = session_id

        await self.session_manager.create_session(
            session_id=session_id,
            cli=cli,
            cwd=cwd,
            model=model,
            effort=effort,
        )

        return {"sessionId": session_id}

    async def _handle_session_load(self, params: dict) -> dict:
        session_id = params.get("sessionId")
        if not session_id:
            raise ACPError(-32602, "Missing sessionId")

        loaded = await self.session_manager.load_session(session_id)
        if not loaded:
            raise ACPError(-32602, f"Session not found: {session_id}")

        self._session_id = session_id
        return {"sessionId": session_id}

    async def _handle_session_prompt(self, params: dict) -> dict:
        session_id = params.get("sessionId") or self._session_id
        if not session_id:
            raise ACPError(-32602, "No active session")

        raw_prompt = params.get("prompt", [])
        if isinstance(raw_prompt, str):
            text = raw_prompt
        else:
            text = ""
            for part in raw_prompt or []:
                if isinstance(part, str):
                    text += part
                elif isinstance(part, dict) and part.get("type") == "text":
                    text += part.get("text", "")

        if not text.strip():
            raise ACPError(-32602, "Empty prompt")

        stop_reason = await self.session_manager.prompt_session(
            session_id=session_id,
            prompt=text,
            send_update=self._send_update,
        )

        return {"stopReason": stop_reason}

    async def _send_update(self, update_type: str, content: str) -> None:
        """Send a session/update notification. This will be wired to the WebSocket."""
        # This is set by the server when connecting the handler
        pass


class ACPConnectionHandler:
    """Manages one WebSocket connection with ACP protocol."""

    def __init__(self, session_manager, ws_connection, dashboard_notifier=None):
        self.session_manager = session_manager
        self.ws = ws_connection
        self.dashboard_notifier = dashboard_notifier
        self.acp = ACPHandler(session_manager)
        # Wire up the update sender
        self.acp._send_update = self._send_update

    async def run(self) -> None:
        """Main loop: read messages, dispatch, send responses."""
        logger.info(f"ACP connection from {self.ws.remote_address}")
        try:
            while True:
                raw = await self.ws.recv()
                if raw is None:
                    break

                logger.debug(f"<-- {raw[:200]}")

                response = await self.acp.handle_message(raw)
                if response:
                    logger.debug(f"--> {response[:200]}")
                    await self.ws.send(response)

                # Notify dashboard
                if self.dashboard_notifier:
                    await self.dashboard_notifier.on_acp_message(raw, response)
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            logger.info(f"ACP connection closed from {self.ws.remote_address}")

    async def _send_update(self, update_type: str, content: str) -> None:
        """Send session/update notification over WebSocket."""
        notification = jsonrpc_notification("session/update", {
            "update": {
                "sessionUpdate": update_type,
                "content": {"text": content},
            }
        })
        await self.ws.send(notification)
        if self.dashboard_notifier:
            await self.dashboard_notifier.on_stream_chunk(
                self.acp._session_id, update_type, content
            )
