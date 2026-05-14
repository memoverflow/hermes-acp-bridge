"""CLI entry point for hermes-acp-bridge."""

import argparse
import asyncio
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hermes-acp-bridge",
        description="ACP WebSocket bridge for Claude Code and Codex CLI",
    )
    parser.add_argument("--port", type=int, default=18080, help="WebSocket server port (default: 18080)")
    parser.add_argument("--dashboard-port", type=int, default=18081, help="Dashboard HTTP port (default: 18081)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--state-dir", default=None, help="Session state directory (default: ~/.hermes-acp-bridge)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    from .server import run_server

    print(f"""
╔══════════════════════════════════════════════════════╗
║          hermes-acp-bridge v0.1.0                    ║
╠══════════════════════════════════════════════════════╣
║  ACP WebSocket : ws://{args.host}:{args.port}       ║
║  Dashboard     : http://{args.host}:{args.dashboard_port}  ║
╚══════════════════════════════════════════════════════╝
""", file=sys.stderr)

    asyncio.run(run_server(
        host=args.host,
        port=args.port,
        dashboard_port=args.dashboard_port,
        state_dir=args.state_dir,
    ))


if __name__ == "__main__":
    main()
