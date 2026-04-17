"""
uD3TN AAP v1 Integration Boundary.

This module is the ONLY place in the Pi agent that talks to uD3TN.
If your uD3TN version changes the wire protocol, only this file needs updating.

Protocol: AAP v1 over Unix domain socket (default: /tmp/ud3tn.socket).

Wire format (verified against vendored uD3TN aap/aap.h):
  Every message starts with one header byte:
    [version:high-nibble=1][type:low-nibble]
  Strings are [len:u16-BE][utf-8 bytes].
  Byte blobs are [len:u64-BE][bytes].

  WELCOME   (0x07)  server→client  [str: node_eid]
  ACK       (0x00)  either→either  (no body)
  NACK      (0x01)  either→either  (no body)
  REGISTER  (0x02)  client→server  [str: agent_id]
  SENDBUNDLE(0x03)  client→server  [str: dest_eid][blob: payload]
  RECVBUNDLE(0x04)  server→client  [str: src_eid][blob: payload]
  SENDCONFIRM(0x05) server→client  [u64: bundle_id]
  PING      (0x08)  either→either  (ACK response)

INTEGRATION NOTE:
  If python-ud3tn-utils (pip install ud3tn-utils) is preferred, replace
  this class with a thin wrapper around ud3tn_utils.aap.AAPClient.
  The interface contract is: connect(), register(agent_id), send(dest, payload),
  recv() -> (src_eid, payload), close().
"""

import logging
import socket
import struct
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_VERSION = 1
_SOCKET_TIMEOUT_S = 5.0

class _MsgType:
    ACK          = 0x00
    NACK         = 0x01
    REGISTER     = 0x02
    SENDBUNDLE   = 0x03
    RECVBUNDLE   = 0x04
    SENDCONFIRM  = 0x05
    CANCELBUNDLE = 0x06
    WELCOME      = 0x07
    PING         = 0x08


def _pack_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _pack_blob(b: bytes) -> bytes:
    return struct.pack("!Q", len(b)) + b


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout as e:
            raise TimeoutError("AAP socket timed out while reading") from e
        if not chunk:
            raise ConnectionError("Socket closed while reading")
        buf += chunk
    return buf


def _read_str(sock: socket.socket) -> str:
    length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    return _recv_exact(sock, length).decode("utf-8")


def _read_blob(sock: socket.socket) -> bytes:
    length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    return _recv_exact(sock, length)


def _pack_header(msg_type: int) -> bytes:
    return bytes([(_VERSION << 4) | (msg_type & 0x0F)])


def _recv_header(sock: socket.socket) -> tuple[int, int]:
    header = _recv_exact(sock, 1)[0]
    return (header >> 4), (header & 0x0F)


class AAPv1Client:
    """
    Minimal synchronous AAP v1 client.

    Usage:
        client = AAPv1Client("/tmp/ud3tn.socket")
        client.connect()
        client.register("telemetry")
        client.send("dtn://mac-ground.dtn/telemetry", b"payload", lifetime_ms=3_600_000)
        src, payload = client.recv()   # blocks
        client.close()
    """

    def __init__(self, socket_path: str = "/tmp/ud3tn.socket") -> None:
        self._socket_path = socket_path
        self._sock: Optional[socket.socket] = None
        self._node_eid: Optional[str] = None
        self._agent_eid: Optional[str] = None
        self._lock = threading.Lock()

    def connect(self) -> str:
        """Connect to uD3TN and read WELCOME. Returns node EID."""
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._socket_path)
        self._sock.settimeout(_SOCKET_TIMEOUT_S)

        version, msg_type = _recv_header(self._sock)
        if version != _VERSION or msg_type != _MsgType.WELCOME:
            raise RuntimeError(
                f"Expected WELCOME, got version={version} type={msg_type:#04x}"
            )
        self._node_eid = _read_str(self._sock)
        logger.info("AAP: connected to uD3TN node %s", self._node_eid)
        return self._node_eid

    def register(self, agent_id: str) -> str:
        """Register agent endpoint. Returns full EID."""
        if not self._sock:
            raise RuntimeError("Not connected")
        payload = _pack_header(_MsgType.REGISTER) + _pack_str(agent_id)
        with self._lock:
            self._sock.sendall(payload)
            version, msg_type = _recv_header(self._sock)
        if version != _VERSION or msg_type != _MsgType.ACK:
            raise RuntimeError(
                f"Expected ACK after REGISTER, got version={version} type={msg_type:#04x}"
            )
        self._agent_eid = f"{self._node_eid}{agent_id}"
        logger.info("AAP: registered as %s", self._agent_eid)
        return self._agent_eid

    def send(self, dest_eid: str, payload: bytes, lifetime_ms: int = 3_600_000) -> None:
        """
        Send a bundle. Blocks until SENDCONFIRM is received.

        NOTE: AAPv1 SENDBUNDLE does not carry bundle lifetime on-wire.
        `lifetime_ms` is accepted for backward call-site compatibility only.
        """
        if not self._sock:
            raise RuntimeError("Not connected")
        msg = (
            _pack_header(_MsgType.SENDBUNDLE)
            + _pack_str(dest_eid)
            + _pack_blob(payload)
        )
        with self._lock:
            self._sock.sendall(msg)
            # Wait for SENDCONFIRM
            version, msg_type = _recv_header(self._sock)
            if msg_type == _MsgType.NACK:
                raise RuntimeError("uD3TN returned NACK for SENDBUNDLE")
            if msg_type != _MsgType.SENDCONFIRM:
                raise RuntimeError(
                    f"Expected SENDCONFIRM, got type={msg_type:#04x}"
                )
            _recv_exact(self._sock, 8)  # bundle_id

    def recv(self) -> Tuple[str, bytes]:
        """Block until a bundle is delivered. Returns (src_eid, payload)."""
        if not self._sock:
            raise RuntimeError("Not connected")
        while True:
            version, msg_type = _recv_header(self._sock)
            if msg_type == _MsgType.RECVBUNDLE:
                src_eid = _read_str(self._sock)
                payload = _read_blob(self._sock)
                return src_eid, payload
            elif msg_type == _MsgType.PING:
                pong = _pack_header(_MsgType.ACK)
                with self._lock:
                    self._sock.sendall(pong)
            else:
                logger.warning("AAP: unexpected message type %#04x, ignoring", msg_type)

    def ping(self) -> bool:
        """Send PING and wait for PONG. Returns True on success."""
        if not self._sock:
            return False
        try:
            with self._lock:
                self._sock.sendall(_pack_header(_MsgType.PING))
                version, msg_type = _recv_header(self._sock)
            return version == _VERSION and msg_type == _MsgType.ACK
        except Exception:
            return False

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        logger.info("AAP: connection closed")
