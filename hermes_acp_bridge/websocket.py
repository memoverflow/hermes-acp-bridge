"""Pure-stdlib WebSocket server implementation (RFC 6455)."""

import asyncio
import base64
import hashlib
import struct
from typing import Optional, Callable, Awaitable


WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Opcodes
OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketConnection:
    """A single WebSocket connection."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.closed = False
        self._close_code: Optional[int] = None

    @property
    def remote_address(self) -> str:
        peername = self.writer.get_extra_info("peername")
        if peername:
            return f"{peername[0]}:{peername[1]}"
        return "unknown"

    async def send(self, message: str) -> None:
        """Send a text frame."""
        if self.closed:
            return
        data = message.encode("utf-8")
        await self._send_frame(OP_TEXT, data)

    async def recv(self) -> Optional[str]:
        """Receive a text message. Returns None on close."""
        while not self.closed:
            frame = await self._read_frame()
            if frame is None:
                self.closed = True
                return None
            opcode, payload = frame
            if opcode == OP_TEXT:
                return payload.decode("utf-8")
            elif opcode == OP_CLOSE:
                self.closed = True
                # Send close back
                await self._send_frame(OP_CLOSE, b"")
                return None
            elif opcode == OP_PING:
                await self._send_frame(OP_PONG, payload)
            # Ignore pong and continuation for simplicity
        return None

    async def close(self, code: int = 1000) -> None:
        """Send close frame."""
        if self.closed:
            return
        self.closed = True
        payload = struct.pack("!H", code)
        try:
            await self._send_frame(OP_CLOSE, payload)
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    async def _send_frame(self, opcode: int, data: bytes) -> None:
        """Send a WebSocket frame."""
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode
        length = len(data)
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(127)
            frame.extend(struct.pack("!Q", length))
        frame.extend(data)
        self.writer.write(bytes(frame))
        await self.writer.drain()

    async def _read_frame(self) -> Optional[tuple[int, bytes]]:
        """Read a WebSocket frame. Returns (opcode, payload) or None."""
        try:
            header = await self.reader.readexactly(2)
        except (asyncio.IncompleteReadError, ConnectionError):
            return None

        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F

        if length == 126:
            raw = await self.reader.readexactly(2)
            length = struct.unpack("!H", raw)[0]
        elif length == 127:
            raw = await self.reader.readexactly(8)
            length = struct.unpack("!Q", raw)[0]

        if masked:
            mask_key = await self.reader.readexactly(4)

        payload = await self.reader.readexactly(length)

        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        return opcode, payload


async def ws_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, path_filter: Optional[str] = None) -> Optional[WebSocketConnection]:
    """Perform WebSocket upgrade handshake. Returns connection or None."""
    request_line = await reader.readline()
    if not request_line:
        return None

    request_text = request_line.decode("utf-8", errors="replace")
    parts = request_text.strip().split()
    if len(parts) < 2:
        return None

    method, path = parts[0], parts[1]
    if method != "GET":
        return None

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

    # Verify WebSocket upgrade
    upgrade = headers.get("upgrade", "").lower()
    ws_key = headers.get("sec-websocket-key", "")
    if upgrade != "websocket" or not ws_key:
        # Not a WebSocket request — return path info for HTTP handling
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        return None

    # Compute accept key
    accept_raw = base64.b64encode(
        hashlib.sha1(ws_key.encode() + WS_MAGIC).digest()
    ).decode()

    # Send upgrade response
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_raw}\r\n"
        "\r\n"
    )
    writer.write(response.encode())
    await writer.drain()

    return WebSocketConnection(reader, writer)


class WebSocketServer:
    """Asyncio WebSocket server."""

    def __init__(self, host: str, port: int, handler: Callable[[WebSocketConnection], Awaitable[None]]):
        self.host = host
        self.port = port
        self.handler = handler
        self._server: Optional[asyncio.Server] = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._on_connection, self.host, self.port
        )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ws = await ws_handshake(reader, writer)
        if ws is None:
            writer.close()
            return
        try:
            await self.handler(ws)
        except Exception:
            pass
        finally:
            await ws.close()
