"""
Mac backend entry point.

Starts the configuration and API services, and can optionally start:
  1. DTN Receiver Bridge  — listens on local uD3TN AAP socket
  2. Config Server        — WebSocket management endpoint (Ethernet, port 8765)
  3. API Server           — REST + WebSocket for frontend (port 8080)

All services share a single Store instance.
"""

import asyncio
import logging
import os
import signal
import sys

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

from config import (
    API_HOST, API_PORT, CONFIG_HOST, CONFIG_PORT, DB_PATH, DEDUP_TTL_S,
    DTN_SOCKET_PATH, ENABLE_DTN_BRIDGE, METRICS_WINDOW_SIZE, REALTIME_DEADLINE_MS,
)
from shared.store import Store
from dtn_receiver_bridge.bridge import DTNReceiverBridge
from api_server.server import APIServer
from config_server.server import ConfigServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mac-backend")


async def main() -> None:
    logger.info("Mac backend starting")

    # ── Shared store ──────────────────────────────────────────────────────────
    store = Store(
        db_path=DB_PATH,
        realtime_deadline_ms=REALTIME_DEADLINE_MS,
        metrics_window_size=METRICS_WINDOW_SIZE,
        dedup_ttl_s=DEDUP_TTL_S,
    )
    store.open()

    # ── Services ──────────────────────────────────────────────────────────────
    config_srv = ConfigServer(store=store, host=CONFIG_HOST, port=CONFIG_PORT)
    api_srv    = APIServer(
        store             = store,
        config_server_send = config_srv.send_command,
        host              = API_HOST,
        port              = API_PORT,
    )
    # Hook store WS broadcast → api_server broadcast
    store.set_ws_broadcast(api_srv.broadcast)

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    loop   = asyncio.get_running_loop()
    stop_ev = asyncio.Event()

    def _stop(sig):
        logger.info("Signal %s — shutting down", sig.name)
        stop_ev.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop, sig)

    # ── Run ───────────────────────────────────────────────────────────────────
    tasks = [
        asyncio.create_task(config_srv.run(), name="config_server"),
        asyncio.create_task(api_srv.run(),    name="api_server"),
        asyncio.create_task(stop_ev.wait(),   name="shutdown_watcher"),
    ]
    if ENABLE_DTN_BRIDGE:
        bridge = DTNReceiverBridge(store=store, socket_path=DTN_SOCKET_PATH)
        tasks.append(asyncio.create_task(bridge.run(), name="dtn_bridge"))
    else:
        logger.info("DTN receiver bridge disabled by configuration")

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    logger.info("Stopping all services")
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    store.close()
    logger.info("Mac backend stopped")


if __name__ == "__main__":
    asyncio.run(main())
