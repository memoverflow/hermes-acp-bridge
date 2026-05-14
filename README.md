# hermes-acp-bridge

ACP (Agent Client Protocol) WebSocket bridge that connects [Hermes Agent](https://github.com/NousResearch/hermes-agent) to Claude Code CLI and Codex CLI.

## Why

Hermes Agent's built-in `delegate_task` uses stdio-based ACP which creates a new process per invocation — sessions die after each call. This bridge upgrades ACP to **WebSocket transport**, enabling:

- **Persistent sessions** — multi-turn conversations with the same CLI instance
- **Multi-session** — run Claude Code and Codex concurrently
- **Real-time streaming** — see agent output as it happens
- **Live dashboard** — monitor all sessions from a web UI

## Architecture

```
┌──────────────┐                              ┌─────────────────────────┐
│ Hermes Agent │◄── ws://localhost:18080 ────►│  hermes-acp-bridge      │
│              │     ACP JSON-RPC 2.0         │  (WebSocket server)     │
└──────────────┘                              └────────────┬────────────┘
                                                           │
                                         ┌─────────────────┼─────────────────┐
                                         ▼                                   ▼
                                   ┌───────────┐                       ┌───────────┐
                                   │Claude Code│                       │ Codex CLI │
                                   │  CLI      │                       │           │
                                   └───────────┘                       └───────────┘

Dashboard: http://localhost:18081  (real-time monitoring)
```

## Quick Start

```bash
# Clone
git clone https://github.com/memoverflow/hermes-acp-bridge.git
cd hermes-acp-bridge

# Run (no install needed — pure stdlib)
python -m hermes_acp_bridge

# Or install
pip install -e .
hermes-acp-bridge
```

Server starts on:
- **ACP WebSocket**: `ws://127.0.0.1:18080`
- **Dashboard**: `http://127.0.0.1:18081`

## Prerequisites

- Python 3.10+
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code` + `claude` auth
- Codex CLI: `npm install -g @openai/codex` + `codex login`

## Usage with Hermes Agent

### Via WebSocket client (Python)

```python
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://localhost:18080") as ws:
        # Initialize
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": 1, "clientInfo": {"name": "hermes"}}
        }))
        print(await ws.recv())

        # Create session
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "session/new",
            "params": {"cli": "claude", "cwd": "/path/to/project"}
        }))
        resp = json.loads(await ws.recv())
        session_id = resp["result"]["sessionId"]

        # Send prompt
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "Write hello world in Go"}]
            }
        }))

        # Receive streaming updates + final result
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("method") == "session/update":
                chunk = msg["params"]["update"]["content"]["text"]
                print(chunk, end="", flush=True)
            elif "result" in msg:
                print(f"\n\nDone: {msg['result']}")
                break

asyncio.run(main())
```

### With Hermes delegate_task (once WebSocket support is added)

```python
delegate_task(
    goal="Write a REST API",
    acp_command="hermes-acp-bridge-client",
    acp_args=["--ws", "ws://localhost:18080", "--cli", "claude"],
)
```

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 18080 | ACP WebSocket server port |
| `--dashboard-port` | 18081 | Dashboard HTTP port |
| `--host` | 127.0.0.1 | Bind address |
| `--log-level` | INFO | Logging level |
| `--state-dir` | ~/.hermes-acp-bridge | Session state directory |

## ACP Protocol Reference

### Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `initialize` | client→server | Handshake, returns capabilities |
| `session/new` | client→server | Create session: `{cli, cwd, model, effort}` |
| `session/load` | client→server | Resume session from disk |
| `session/prompt` | client→server | Send prompt, triggers streaming |
| `session/cancel` | client→server (notification) | Cancel running prompt |
| `session/update` | server→client (notification) | Streaming chunks |

### session/new params

```json
{
  "cli": "claude",          // "claude" or "codex"
  "cwd": "/path/to/dir",   // working directory
  "model": "opus",          // optional model override
  "effort": "high"          // optional reasoning effort
}
```

### session/update notification

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "update": {
      "sessionUpdate": "agent_message_chunk",  // or "agent_thought_chunk"
      "content": {"text": "Here is the code..."}
    }
  }
}
```

## Dashboard

Open `http://localhost:18081` in your browser for real-time monitoring:

- **Active Sessions** — see all running sessions with CLI type, status, message count
- **Live Stream** — watch agent output in real-time as it's generated
- **Event Timeline** — chronological log of all ACP messages
- **Metrics** — total sessions, messages, events

The dashboard uses WebSocket for live updates — no page refresh needed.

## Project Structure

```
hermes-acp-bridge/
├── hermes_acp_bridge/
│   ├── __init__.py          # Package + version
│   ├── __main__.py          # CLI entry point
│   ├── server.py            # Main asyncio server
│   ├── acp.py               # ACP JSON-RPC protocol
│   ├── session.py           # Session management + persistence
│   ├── websocket.py         # Pure stdlib WebSocket (RFC 6455)
│   ├── drivers/
│   │   ├── base.py          # Abstract driver
│   │   ├── claude.py        # Claude Code driver
│   │   └── codex.py         # Codex CLI driver
│   └── dashboard/
│       ├── __init__.py      # Dashboard server
│       └── static/          # HTML/CSS/JS
├── tests/
├── pyproject.toml
├── LICENSE (MIT)
└── README.md
```

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make changes (pure stdlib only — no third-party deps!)
4. Run tests: `python -m pytest tests/`
5. Submit a PR

## License

MIT — see [LICENSE](LICENSE)
