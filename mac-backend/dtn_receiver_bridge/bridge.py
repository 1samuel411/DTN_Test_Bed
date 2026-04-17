"""
DTN Receiver Bridge.

Listens on the local uD3TN AAP socket for delivered bundles.
Decodes JSON payloads, identifies message type, and ingests into the Store.

This service is separate from the API server so the two can be restarted
independently and the AAP connection is not on the API's hot path.

Architecture:
  uD3TN (Mac) ──AAP socket──► bridge.recv() ──► store.ingest_bundle()
                                                       ↓
                                              API server reads Store
                                              WS broadcast to frontend

The bridge registers TWO agent endpoints on uD3TN:
  dtn://mac-ground.dtn/telemetry  — altitude telemetry bundles
  dtn://mac-ground.dtn/status     — GPS status event bundles

Both endpoints use the same AAPv1Client but separate connections.
"""

import asyncio
import json
import logging
import os
import sys

# Add parent to path so relative imports work when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.schemas import AltitudeTelemetry, GPSStatusMessage
from shared.store import Store

logger = logging.getLogger(__name__)


# ── Minimal inline AAP client (same protocol as pi-agent/dtn_sender/dtn_adapter.py) ──

import socket
import struct
import threading
from typing import Optional, Tuple

_AAP_VERSION = 1

class _MsgType:
    ACK         = 0x00
    NACK        = 0x01
    REGISTER    = 0x02
    SENDBUNDLE  = 0x03
    RECVBUNDLE  = 0x04
    SENDCONFIRM = 0x05
    WELCOME     = 0x07
    PING        = 0x08


def _recv_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed")
        buf += chunk
    return buf


def _read_str(s: socket.socket) -> str:
    length = struct.unpack("!H", _recv_exact(s, 2))[0]
    return _recv_exact(s, length).decode("utf-8")


def _read_blob(s: socket.socket) -> bytes:
    length = struct.unpack("!Q", _recv_exact(s, 8))[0]
    return _recv_exact(s, length)


def _pack_str(v: str) -> bytes:
    b = v.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _pack_header(msg_type: int) -> bytes:
    return bytes([(_AAP_VERSION << 4) | (msg_type & 0x0F)])


def _recv_header(s: socket.socket) -> Tuple[int, int]:
    header = _recv_exact(s, 1)[0]
    return (header >> 4), (header & 0x0F)


class _ReceiverAAP:
    """Blocking AAP receiver that registers an endpoint and yields bundles."""

    def __init__(self, socket_path: str, agent_id: str) -> None:
        self._socket_path = socket_path
        self._agent_id    = agent_id
        self._sock: Optional[socket.socket] = None
        self._lock        = threading.Lock()

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._socket_path)

        version, msg_type = _recv_header(self._sock)
        if version != _AAP_VERSION or msg_type != _MsgType.WELCOME:
            raise RuntimeError(f"Expected WELCOME, got version={version} type={msg_type:#04x}")
        node_eid = _read_str(self._sock)
        logger.info("AAP (receiver/%s): connected to %s", self._agent_id, node_eid)

        # Register
        reg = _pack_header(_MsgType.REGISTER) + _pack_str(self._agent_id)
        with self._lock:
            self._sock.sendall(reg)
            version, msg_type = _recv_header(self._sock)
        if version != _AAP_VERSION or msg_type != _MsgType.ACK:
            raise RuntimeError(
                f"Expected ACK after REGISTER, got version={version} type={msg_type:#04x}"
            )

    def recv_bundle(self) -> Tuple[str, bytes]:
        while True:
            version, msg_type = _recv_header(self._sock)
            if msg_type == _MsgType.RECVBUNDLE:
                src_eid = _read_str(self._sock)
                payload = _read_blob(self._sock)
                return src_eid, payload
            elif msg_type == _MsgType.PING:
                with self._lock:
                    self._sock.sendall(_pack_header(_MsgType.ACK))
            else:
                logger.debug("AAP receiver: ignoring msg type %#04x", msg_type)

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None


# ── Bridge service ────────────────────────────────────────────────────────────

class DTNReceiverBridge:
    def __init__(self, store: Store, socket_path: str) -> None:
        self._store       = store
        self._socket_path = socket_path
        self._running     = False

    async def run(self) -> None:
        self._running = True
        logger.info("DTN receiver bridge starting, AAP socket: %s", self._socket_path)

        # Run two receiver loops concurrently
        await asyncio.gather(
            self._receive_loop("telemetry"),
            self._receive_loop("status"),
        )

    def stop(self) -> None:
        self._running = False

    async def _receive_loop(self, agent_id: str) -> None:
        loop = asyncio.get_event_loop()
        backoff = 1.0

        while self._running:
            client = _ReceiverAAP(self._socket_path, agent_id)
            try:
                await loop.run_in_executor(None, client.connect)
                backoff = 1.0
                logger.info("DTN bridge [%s]: listening for bundles", agent_id)

                while self._running:
                    src_eid, raw = await loop.run_in_executor(None, client.recv_bundle)
                    await self._handle_bundle(src_eid, raw)

            except Exception as e:
                logger.error("DTN bridge [%s] error: %s. Retry in %.0fs", agent_id, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                client.close()

    async def _handle_bundle(self, src_eid: str, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8"))
            msg_type = data.get("msg_type")

            if msg_type == "altitude_telemetry":
                msg = AltitudeTelemetry(**data)
            elif msg_type == "gps_status":
                msg = GPSStatusMessage(**data)
            else:
                logger.warning("Unknown bundle msg_type=%s from %s", msg_type, src_eid)
                return

            self._store.ingest_bundle(msg, raw_size=len(raw))
            logger.debug(
                "Bundle ingested: type=%s src=%s size=%d",
                msg_type, src_eid, len(raw),
            )
        except json.JSONDecodeError as e:
            logger.error("Bundle JSON decode error: %s", e)
        except Exception as e:
            logger.exception("Bundle handling error: %s", e)
