"""Dashboard HTTP + WebSocket server."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from ..websocket import WebSocketConnection, ws_handshake

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class DashboardServer:
    """Serves dashboard UI and provides real-time updates via WebSocket."""

    def __init__(self, host: str, port: int, session_manager):
        self.host = host
        self.port = port
        self.session_manager = session_manager
        self._server: Optional[asyncio.Server] = None
        self._ws_clients: list[WebSocketConnection] = []
        self._event_log: list[dict] = []
        self.start_time = time.time()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )

    async def stop(self) -> None:
        for client in self._ws_clients:
            await client.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle incoming HTTP or WebSocket connection."""
        request_line = await reader.readline()
        if not request_line:
            writer.close()
            return

        request_text = request_line.decode("utf-8", errors="replace").strip()
        parts = request_text.split()
        if len(parts) < 2:
            writer.close()
            return

        method, path = parts[0], parts[1]

        # Read headers
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if ":" in decoded:
                key, value = decoded.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        # WebSocket upgrade for /ws
        if path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
            ws_key = headers.get("sec-websocket-key", "")
            if ws_key:
                await self._upgrade_websocket(reader, writer, ws_key)
                return

        # Regular HTTP
        if path == "/api/sessions":
            await self._serve_api_sessions(writer)
        elif path == "/api/events":
            await self._serve_api_events(writer)
        else:
            await self._serve_static(path, writer)

    async def _upgrade_websocket(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ws_key: str) -> None:
        """Complete WebSocket handshake and stream updates."""
        import base64
        import hashlib

        WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept_raw = base64.b64encode(
            hashlib.sha1(ws_key.encode() + WS_MAGIC).digest()
        ).decode()

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_raw}\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        await writer.drain()

        ws = WebSocketConnection(reader, writer)
        self._ws_clients.append(ws)

        # Send initial state
        await ws.send(json.dumps({"type": "init", "data": self._get_state()}))

        try:
            while True:
                msg = await ws.recv()
                if msg is None:
                    break
        except Exception:
            pass
        finally:
            self._ws_clients.remove(ws)

    async def _serve_static(self, path: str, writer: asyncio.StreamWriter) -> None:
        """Serve static files for dashboard."""
        if path == "/" or path == "":
            path = "/index.html"

        file_path = STATIC_DIR / path.lstrip("/")
        if not file_path.exists() or not file_path.is_file():
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        content = file_path.read_bytes()
        content_type = self._guess_content_type(path)
        header = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(content)}\r\n"
            f"Cache-Control: no-cache\r\n"
            f"\r\n"
        )
        writer.write(header.encode() + content)
        await writer.drain()
        writer.close()

    async def _serve_api_sessions(self, writer: asyncio.StreamWriter) -> None:
        sessions = [s.to_dict() for s in self.session_manager.active_sessions.values()]
        body = json.dumps(sessions).encode()
        header = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        writer.write(header.encode() + body)
        await writer.drain()
        writer.close()

    async def _serve_api_events(self, writer: asyncio.StreamWriter) -> None:
        body = json.dumps(self._event_log[-100:]).encode()
        header = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        writer.write(header.encode() + body)
        await writer.drain()
        writer.close()

    def _guess_content_type(self, path: str) -> str:
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        elif path.endswith(".css"):
            return "text/css"
        elif path.endswith(".js"):
            return "application/javascript"
        elif path.endswith(".json"):
            return "application/json"
        return "application/octet-stream"

    def _get_state(self) -> dict:
        return {
            "sessions": [s.to_dict() for s in self.session_manager.active_sessions.values()],
            "uptime": time.time() - self.start_time,
            "total_events": len(self._event_log),
        }

    async def on_acp_message(self, request: str, response: Optional[str]) -> None:
        """Called when an ACP message is exchanged."""
        event = {
            "time": time.time(),
            "type": "acp_message",
            "request": request[:500],
            "response": (response or "")[:500],
        }
        self._event_log.append(event)
        await self._broadcast({"type": "event", "data": event})

    async def on_stream_chunk(self, session_id: Optional[str], update_type: str, content: str) -> None:
        """Called when a streaming chunk is sent."""
        event = {
            "time": time.time(),
            "type": "stream",
            "session_id": session_id,
            "update_type": update_type,
            "content": content[:1000],
        }
        self._event_log.append(event)
        await self._broadcast({"type": "stream", "data": event})

    async def _broadcast(self, message: dict) -> None:
        """Broadcast to all dashboard WebSocket clients."""
        raw = json.dumps(message)
        dead: list[WebSocketConnection] = []
        for client in self._ws_clients:
            try:
                await client.send(raw)
            except Exception:
                dead.append(client)
        for d in dead:
            self._ws_clients.remove(d)
