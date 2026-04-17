"""
Config Server.

Accepts one active management WebSocket from the Pi (on Ethernet); a new connection replaces the previous one.
Receives periodic PiStatusReport messages and updates the Store.
Provides a send_command() coroutine used by the API server to push commands to the Pi.

Also provides a REST sub-server for the frontend to submit commands directly:
  POST /control/command  — same as API server /api/command

Architecture:
  Pi ──ws://eth:8765/pi──► config_server (receives status, sends commands)
  API server ──────────────► config_server.send_command(cmd_dict)
"""

import asyncio
import json
import logging
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol

from shared.schemas import DTNSendCounterMessage, PiStatusReport
from shared.store import Store

logger = logging.getLogger(__name__)


class ConfigServer:
    def __init__(self, store: Store, host: str, port: int) -> None:
        self._store = store
        self._host  = host
        self._port  = port
        self._pi_ws: Optional[WebSocketServerProtocol] = None
        self._running = False
        self._send_lock = asyncio.Lock()
        self._conn_lock = asyncio.Lock()

    async def send_command(self, cmd: dict) -> None:
        """
        Send a command to the Pi over the active management WebSocket.
        Called by the API server's /api/command endpoint.
        """
        async with self._send_lock:
            if self._pi_ws is None:
                raise RuntimeError("Pi management connection not available")
            await self._pi_ws.send(json.dumps(cmd))
            logger.info("Config: sent command to Pi: %s", cmd.get("cmd"))

    async def run(self) -> None:
        self._running = True
        logger.info("Config server listening on %s:%d", self._host, self._port)

        async with websockets.serve(
            self._handle_pi,
            self._host,
            self._port,
            ping_interval = 10,
            ping_timeout  = 20,
        ):
            while self._running:
                await asyncio.sleep(1.0)

    def stop(self) -> None:
        self._running = False

    @staticmethod
    def _ws_path(ws: WebSocketServerProtocol) -> str:
        path = getattr(ws, "path", None)
        if path:
            return path

        request = getattr(ws, "request", None)
        request_path = getattr(request, "path", None)
        return request_path or ""

    async def _handle_pi(self, ws: WebSocketServerProtocol) -> None:
        path = self._ws_path(ws)
        if path != "/pi":
            await ws.close(1008, "Wrong path — connect to /pi")
            return

        async with self._conn_lock:
            if self._pi_ws is not None:
                old = self._pi_ws
                self._pi_ws = ws
                logger.warning(
                    "Config: replacing previous Pi connection %s with new client %s",
                    old.remote_address,
                    ws.remote_address,
                )
                try:
                    await old.close(1001, "Replaced by new Pi connection")
                except Exception as e:
                    logger.debug("Config: while closing superseded Pi ws: %s", e)
            else:
                self._pi_ws = ws

        remote = ws.remote_address
        logger.info("Config: Pi connected from %s", remote)

        try:
            async for raw in ws:
                await self._handle_message(raw)
        except Exception as e:
            logger.warning("Config: Pi connection error: %s", e)
        finally:
            if self._pi_ws is ws:
                self._pi_ws = None
            logger.info("Config: Pi disconnected from %s", remote)

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            msg_type = data.get("msg_type")

            if msg_type == "pi_status":
                status = PiStatusReport(**data)
                self._store.update_pi_status(status)
            elif msg_type == "dtn_send_counter":
                counter_update = DTNSendCounterMessage(**data)
                self._store.ingest_dtn_send_counter(counter_update)
            elif data.get("pong"):
                logger.debug("Config: received pong from Pi")
            else:
                logger.debug("Config: unrecognized message type: %s", msg_type)
        except Exception as e:
            logger.error("Config: error handling Pi message: %s", e)
