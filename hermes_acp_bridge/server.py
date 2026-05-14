"""Main server: runs both ACP WebSocket and Dashboard HTTP."""

import asyncio
import logging
from typing import Optional

from .websocket import WebSocketServer, WebSocketConnection
from .acp import ACPConnectionHandler
from .session import SessionManager
from .dashboard.handler import DashboardServer

logger = logging.getLogger(__name__)


class ACPBridgeServer:
    """Main server coordinating ACP WebSocket and Dashboard."""

    def __init__(self, host: str, port: int, dashboard_port: int, state_dir: Optional[str] = None):
        self.host = host
        self.port = port
        self.dashboard_port = dashboard_port
        self.session_manager = SessionManager(state_dir=state_dir)
        self.dashboard = DashboardServer(host, dashboard_port, self.session_manager)
        self.ws_server = WebSocketServer(host, port, self._handle_acp_connection)

    async def _handle_acp_connection(self, ws: WebSocketConnection) -> None:
        """Handle a new ACP WebSocket connection."""
        handler = ACPConnectionHandler(
            session_manager=self.session_manager,
            ws_connection=ws,
            dashboard_notifier=self.dashboard,
        )
        await handler.run()

    async def start(self) -> None:
        """Start both servers."""
        await self.ws_server.start()
        await self.dashboard.start()
        logger.info(f"ACP WebSocket server listening on ws://{self.host}:{self.port}")
        logger.info(f"Dashboard available at http://{self.host}:{self.dashboard_port}")

    async def stop(self) -> None:
        """Stop all servers and cleanup."""
        await self.session_manager.cleanup()
        await self.ws_server.stop()
        await self.dashboard.stop()


async def run_server(host: str, port: int, dashboard_port: int, state_dir: Optional[str] = None) -> None:
    """Run the bridge server until interrupted."""
    server = ACPBridgeServer(host, port, dashboard_port, state_dir)
    await server.start()

    try:
        # Run forever
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()
