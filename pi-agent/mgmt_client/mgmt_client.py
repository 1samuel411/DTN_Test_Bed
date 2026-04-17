"""
Management Client.

Maintains a persistent WebSocket connection to the Mac Config Server over Ethernet.
This is the ONLY service on the Pi that communicates over Ethernet.

Responsibilities:
  • Send periodic PiStatusReport every HEARTBEAT seconds
  • Receive and dispatch commands: set_mode, set_emulation, revert_emulation,
    set_baudrate, clear_queue, set_link_manager_config, ping
  • Reconnect automatically on disconnect with exponential backoff (capped at 60 s)
"""

import asyncio
import json
import logging
import time
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config import (
    MGMT_HEARTBEAT_S,
    MGMT_SERVER_IP,
    MGMT_SERVER_PORT,
    MGMT_STATUS_PUSH_S,
)
from schemas import (
    ClearQueueCommand,
    DTNSendCounterMessage,
    PingCommand,
    PiStatusReport,
    RevertEmulationCommand,
    SetBaudrateCommand,
    SetEmulationCommand,
    SetExperimentModeCommand,
    SetGpsSendFrequencyCommand,
    SetLinkManagerConfigCommand,
    SetModeCommand,
)

logger = logging.getLogger(__name__)

_CMD_MAP = {
    "set_mode":             SetModeCommand,
    "set_experiment_mode":  SetExperimentModeCommand,
    "set_emulation":        SetEmulationCommand,
    "revert_emulation":     RevertEmulationCommand,
    "set_baudrate":         SetBaudrateCommand,
    "set_gps_send_frequency": SetGpsSendFrequencyCommand,
    "clear_queue":          ClearQueueCommand,
    "set_link_manager_config": SetLinkManagerConfigCommand,
    "ping":                 PingCommand,
}


class MgmtClient:
    def __init__(
        self,
        get_status: Callable[[], PiStatusReport],
        on_set_mode:            Callable[[SetModeCommand],            None],
        on_set_experiment_mode: Callable[[SetExperimentModeCommand],  None],
        on_set_emulation:       Callable[[SetEmulationCommand],       None],
        on_revert:              Callable[[RevertEmulationCommand],    None],
        on_set_baudrate:        Callable[[SetBaudrateCommand],        None],
        on_set_gps_send_frequency: Callable[[SetGpsSendFrequencyCommand], None],
        on_clear_queue:         Callable[[ClearQueueCommand],         None],
        on_set_link_manager_config: Callable[[SetLinkManagerConfigCommand], None],
    ) -> None:
        self._get_status            = get_status
        self._on_set_mode           = on_set_mode
        self._on_set_experiment_mode = on_set_experiment_mode
        self._on_set_emulation      = on_set_emulation
        self._on_revert             = on_revert
        self._on_set_baudrate       = on_set_baudrate
        self._on_set_gps_send_frequency = on_set_gps_send_frequency
        self._on_clear_queue        = on_clear_queue
        self._on_set_link_manager_config = on_set_link_manager_config

        self._running  = False
        self._ws       = None
        self._backoff  = 1.0
        self._send_lock = asyncio.Lock()
        self._counter_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2048)

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def run(self) -> None:
        self._running = True
        url = f"ws://{MGMT_SERVER_IP}:{MGMT_SERVER_PORT}/pi"
        logger.info("Management client target: %s", url)

        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=MGMT_HEARTBEAT_S,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._backoff = 1.0
                    logger.info("Management: connected to Mac over Ethernet")
                    await asyncio.gather(
                        self._send_loop(ws),
                        self._counter_send_loop(ws),
                        self._recv_loop(ws),
                    )
            except (ConnectionClosed, OSError, WebSocketException) as e:
                logger.warning("Management: disconnected (%s). Retry in %.0fs", e, self._backoff)
            except Exception as e:
                logger.exception("Management: unexpected error: %s", e)
            finally:
                self._ws = None

            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 60.0)

    def stop(self) -> None:
        self._running = False

    def publish_dtn_send_counter(self, msg: DTNSendCounterMessage) -> None:
        """
        Best-effort enqueue of per-send counter updates for immediate delivery.
        """
        try:
            self._counter_queue.put_nowait(msg.model_dump_json())
        except asyncio.QueueFull:
            logger.warning("Management counter queue full; dropping dtn_send_counter")

    async def _send_loop(self, ws) -> None:
        """
        Emit status updates at high cadence when values change.

        If nothing changes, keep sending a heartbeat status frame every
        MGMT_HEARTBEAT_S seconds.
        """
        last_payload: Optional[str] = None
        last_sent_ts = 0.0
        sleep_s = max(0.2, MGMT_STATUS_PUSH_S)

        while self._running:
            try:
                report = self._get_status()
                payload = report.model_dump_json()
                now = time.monotonic()
                due_heartbeat = (now - last_sent_ts) >= MGMT_HEARTBEAT_S
                changed = payload != last_payload

                if changed or due_heartbeat:
                    async with self._send_lock:
                        await ws.send(payload)
                    last_payload = payload
                    last_sent_ts = now
            except Exception as e:
                logger.error("Management send error: %s", e)
                raise
            await asyncio.sleep(sleep_s)

    async def _counter_send_loop(self, ws) -> None:
        while self._running:
            raw = await self._counter_queue.get()
            try:
                async with self._send_lock:
                    await ws.send(raw)
            except Exception as e:
                logger.error("Management counter send error: %s", e)
                raise

    async def _recv_loop(self, ws) -> None:
        """Receive and dispatch commands from the config server."""
        async for raw in ws:
            try:
                data = json.loads(raw)
                cmd_type = data.get("cmd")
                if cmd_type not in _CMD_MAP:
                    logger.warning("Unknown mgmt command: %s", cmd_type)
                    continue

                model_cls = _CMD_MAP[cmd_type]
                cmd = model_cls(**data)
                await self._dispatch(cmd)
            except Exception as e:
                logger.error("Failed to process command %r: %s", raw[:200], e)

    async def _dispatch(self, cmd) -> None:
        logger.info("Dispatching command: %s", cmd.cmd)
        try:
            if isinstance(cmd, SetExperimentModeCommand):
                self._on_set_experiment_mode(cmd)
            elif isinstance(cmd, SetModeCommand):
                self._on_set_mode(cmd)
            elif isinstance(cmd, SetEmulationCommand):
                self._on_set_emulation(cmd)
            elif isinstance(cmd, RevertEmulationCommand):
                self._on_revert(cmd)
            elif isinstance(cmd, SetBaudrateCommand):
                self._on_set_baudrate(cmd)
            elif isinstance(cmd, SetGpsSendFrequencyCommand):
                self._on_set_gps_send_frequency(cmd)
            elif isinstance(cmd, ClearQueueCommand):
                self._on_clear_queue(cmd)
            elif isinstance(cmd, SetLinkManagerConfigCommand):
                self._on_set_link_manager_config(cmd)
            elif isinstance(cmd, PingCommand):
                if self._ws:
                    async with self._send_lock:
                        await self._ws.send(json.dumps({"pong": True, "ts": time.time()}))
        except Exception as e:
            logger.error("Error dispatching %s: %s", type(cmd).__name__, e)
