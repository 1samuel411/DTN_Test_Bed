"""
DTN Sender service.

Pulls messages from the QueueManager and delivers them via uD3TN AAP.
Tracks per-link byte / bundle counters (source of truth for DTN accounting).

Experiment mode behaviour:
  single_link_wifi / single_link_lte / adaptive:
    • Sends each bundle once via the active link's uD3TN socket.
    • Tags AltitudeTelemetry with send_link, send_monotonic before dispatch.

  redundant:
    • Sends each bundle twice — once via the WiFi uD3TN socket and once via
      the LTE uD3TN socket — concurrently using asyncio.gather.
    • Both copies share the same packet_id; send_link differs.
    • The Mac receiver's dedup cache discards the later-arriving duplicate.
    • Requires two uD3TN instances on the Pi:
        DTN_SOCKET_PATH_WIFI  (default = DTN_SOCKET_PATH)
        DTN_SOCKET_PATH_LTE   (default = DTN_SOCKET_PATH)
      If both env vars resolve to the same path, redundant mode degrades to
      sending twice via the same socket (demonstrates dedup logic, not multi-path).

General:
  • While active_link is "none" (and not in redundant mode), waits on link_change_event.
  • On AAP send failure, sleeps briefly and retries (bundle stays in flight).
  • GPS status events use a separate DTN endpoint (dtn://mac-ground.dtn/status)
    so the receiver can distinguish them without parsing the payload.
"""

import asyncio
import inspect
import json
import logging
import time
from typing import Awaitable, Callable, Optional

from config import (
    DTN_AGENT_STATUS, DTN_AGENT_TELEM,
    DTN_BUNDLE_LIFETIME_S, DTN_DEST_NODE,
    DTN_SOCKET_PATH, DTN_SOCKET_PATH_WIFI, DTN_SOCKET_PATH_LTE,
)
from queue_manager.queue_manager import QueueManager
from schemas import (
    AltitudeTelemetry,
    DTNSendCounterMessage,
    GPSStatusMessage,
    LinkScores,
    TelemetryMessage,
)
from .dtn_adapter import AAPv1Client

logger = logging.getLogger(__name__)


class DTNSender:
    def __init__(
        self,
        queue:              QueueManager,
        link_change_event:  asyncio.Event,
        get_active_link:    Callable[[], str],
        get_experiment_mode: Callable[[], str] = lambda: "single_link_wifi",
        get_link_scores:    Callable[[], dict] = lambda: {"wifi": None, "lte": None},
        get_experiment_session_id: Callable[[], str] = lambda: "",
        get_selected_link: Callable[[], str] = lambda: "wifi",
        get_decision_reason: Callable[[], str] = lambda: "baseline",
        get_queue_depth: Callable[[], int] = lambda: 0,
        device_id: str = "pi-dtn-01",
        emit_send_counter: Optional[
            Callable[[DTNSendCounterMessage], Optional[Awaitable[None]]]
        ] = None,
    ) -> None:
        self._queue              = queue
        self._link_event         = link_change_event
        self._get_active_link    = get_active_link
        self._get_experiment_mode = get_experiment_mode
        self._get_link_scores    = get_link_scores
        self._get_experiment_session_id = get_experiment_session_id
        self._get_selected_link = get_selected_link
        self._get_decision_reason = get_decision_reason
        self._get_queue_depth = get_queue_depth
        self._device_id = device_id
        self._emit_send_counter = emit_send_counter
        self._running            = False

        # Per-link cumulative counters
        self._bytes_wifi    = 0
        self._bytes_lte     = 0
        self._bundles_wifi  = 0
        self._bundles_lte   = 0
        self._failures_wifi = 0
        self._failures_lte  = 0
        self._retries_wifi  = 0
        self._retries_lte   = 0

        # AAP clients for single-link / adaptive modes (one socket)
        self._client_telem:  Optional[AAPv1Client] = None
        self._client_status: Optional[AAPv1Client] = None

        # AAP clients for redundant mode (two sockets: wifi + lte)
        self._client_telem_wifi:   Optional[AAPv1Client] = None
        self._client_status_wifi:  Optional[AAPv1Client] = None
        self._client_telem_lte:    Optional[AAPv1Client] = None
        self._client_status_lte:   Optional[AAPv1Client] = None

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def counters(self) -> dict:
        return {
            "bytes_wifi":   self._bytes_wifi,
            "bytes_lte":    self._bytes_lte,
            "bundles_wifi": self._bundles_wifi,
            "bundles_lte":  self._bundles_lte,
            "failures_wifi": self._failures_wifi,
            "failures_lte":  self._failures_lte,
            "retries_wifi":  self._retries_wifi,
            "retries_lte":   self._retries_lte,
        }

    async def run(self) -> None:
        self._running = True
        logger.info("DTN sender started")
        inflight: Optional[TelemetryMessage] = None

        while self._running:
            mode = self._get_experiment_mode()

            # In non-redundant modes, block if no link is available
            if mode != "redundant":
                active_link = self._get_active_link()
                if active_link == "none":
                    logger.info("DTN sender: no active link, waiting for link restore")
                    self._link_event.clear()
                    await self._link_event.wait()
                    logger.info("DTN sender: link event received, resuming")
                    continue

            if inflight is None:
                try:
                    inflight = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

            sent = await self._dispatch(inflight, mode)
            if sent:
                self._queue.task_done()
                inflight = None
            else:
                self._record_retry(mode)

    def stop(self) -> None:
        self._running = False
        self._close_all_clients()

    # ── Dispatch by experiment mode ──────────────────────────────────────────

    async def _dispatch(self, msg: TelemetryMessage, mode: str) -> bool:
        """Route message to the correct send strategy. Returns True on success."""
        if mode == "redundant" and isinstance(msg, AltitudeTelemetry):
            return await self._send_redundant(msg)
        else:
            return await self._send_single(msg)

    # ── Single-link send (single_link_wifi / single_link_lte / adaptive) ─────

    async def _send_single(self, msg: TelemetryMessage) -> bool:
        """Send one bundle over the currently active link."""
        if not self._ensure_connected_single():
            await asyncio.sleep(2.0)
            return False

        active_link = self._get_active_link()

        # Tag AltitudeTelemetry with send-time metadata
        if isinstance(msg, AltitudeTelemetry):
            scores_raw = self._get_link_scores()
            send_monotonic = time.monotonic()
            msg = msg.model_copy(update={
                "experiment_session_id": self._get_experiment_session_id(),
                "send_link":       active_link,
                "send_monotonic":  send_monotonic,
                "experiment_mode": self._get_experiment_mode(),
                "selected_link":   self._get_selected_link(),
                "decision_reason": self._get_decision_reason(),
                "active_link":     active_link,
                "link_scores": LinkScores(
                    wifi=scores_raw.get("wifi"),
                    lte=scores_raw.get("lte"),
                ) if self._get_experiment_mode() == "adaptive" else None,
                "queue_depth_at_send": self._get_queue_depth(),
                "queue_wait_ms": max(0.0, (send_monotonic - msg.monotonic_ts) * 1000.0),
            })

        ok = await self._send_via_clients(
            msg, self._client_telem, self._client_status, active_link,
        )
        if not ok:
            self._close_single_clients()
        return ok

    # ── Redundant send (both links concurrently) ─────────────────────────────

    async def _send_redundant(self, msg: AltitudeTelemetry) -> bool:
        """
        Send the same logical packet over WiFi and LTE concurrently.
        Both copies carry the same packet_id; send_link differs.
        Returns True when at least one copy succeeds.
        """
        if not self._ensure_connected_redundant():
            await asyncio.sleep(2.0)
            return False

        send_mono = time.monotonic()
        session_id = self._get_experiment_session_id()
        queue_depth_at_send = self._get_queue_depth()
        queue_wait_ms = max(0.0, (send_mono - msg.monotonic_ts) * 1000.0)

        # Copy A — WiFi
        msg_wifi = msg.model_copy(update={
            "experiment_session_id": session_id,
            "selected_link":   "both",
            "decision_reason": "redundant",
            "send_link":       "wifi",
            "send_monotonic":  send_mono,
            "experiment_mode": "redundant",
            "active_link":     self._get_active_link(),
            "link_scores":     None,
            "queue_depth_at_send": queue_depth_at_send,
            "queue_wait_ms": queue_wait_ms,
        })
        # Copy B — LTE (same packet_id — the only field that stays the same)
        msg_lte = msg.model_copy(update={
            "experiment_session_id": session_id,
            "selected_link":   "both",
            "decision_reason": "redundant",
            "send_link":       "lte",
            "send_monotonic":  send_mono,
            "experiment_mode": "redundant",
            "active_link":     self._get_active_link(),
            "link_scores":     None,
            "queue_depth_at_send": queue_depth_at_send,
            "queue_wait_ms": queue_wait_ms,
        })

        results = await asyncio.gather(
            self._send_via_clients(msg_wifi, self._client_telem_wifi,
                                   self._client_status_wifi, "wifi"),
            self._send_via_clients(msg_lte,  self._client_telem_lte,
                                   self._client_status_lte,  "lte"),
            return_exceptions=True,
        )

        wifi_ok = results[0] is True
        lte_ok  = results[1] is True

        if not wifi_ok:
            self._close_redundant_clients("wifi")
        if not lte_ok:
            self._close_redundant_clients("lte")

        if not wifi_ok and not lte_ok:
            logger.error("Redundant send failed on both links")
            await asyncio.sleep(2.0)
            return False

        logger.debug(
            "Redundant send: wifi=%s lte=%s  packet_id=%s",
            "ok" if wifi_ok else "fail",
            "ok" if lte_ok  else "fail",
            msg.packet_id,
        )
        return True

    # ── Low-level send helper ────────────────────────────────────────────────

    async def _send_via_clients(
        self,
        msg:           TelemetryMessage,
        client_telem:  Optional[AAPv1Client],
        client_status: Optional[AAPv1Client],
        link:          str,
    ) -> bool:
        if isinstance(msg, GPSStatusMessage):
            dest   = f"{DTN_DEST_NODE}{DTN_AGENT_STATUS}"
            client = client_status
        else:
            dest   = f"{DTN_DEST_NODE}{DTN_AGENT_TELEM}"
            client = client_telem

        if client is None:
            return False

        payload     = json.dumps(msg.model_dump()).encode("utf-8")
        lifetime_ms = DTN_BUNDLE_LIFETIME_S * 1000
        loop        = asyncio.get_event_loop()

        try:
            await loop.run_in_executor(
                None,
                lambda: client.send(dest, payload, lifetime_ms=lifetime_ms),
            )
        except Exception as e:
            logger.error("DTN send failed (link=%s): %s", link, e)
            if link == "wifi":
                self._failures_wifi += 1
            elif link == "lte":
                self._failures_lte += 1
            return False

        payload_len = len(payload)
        if link == "wifi":
            self._bytes_wifi   += payload_len
            self._bundles_wifi += 1
        elif link == "lte":
            self._bytes_lte   += payload_len
            self._bundles_lte += 1

        logger.debug(
            "DTN sent %d bytes via %s → %s (seq=%s pid=%s)",
            payload_len, link, dest,
            getattr(msg, "sequence_number", "status"),
            getattr(msg, "packet_id", "-"),
        )
        self._publish_send_counter(msg, link, payload_len)
        return True

    def _publish_send_counter(self, msg: TelemetryMessage, link: str, payload_len: int) -> None:
        if self._emit_send_counter is None:
            return
        if link not in ("wifi", "lte"):
            return

        payload = DTNSendCounterMessage(
            device_id=self._device_id,
            link=link,
            bundle_msg_type=msg.msg_type,
            sequence_number=getattr(msg, "sequence_number", None),
            packet_id=getattr(msg, "packet_id", None),
            payload_bytes=payload_len,
            dtn_bytes_sent_wifi=self._bytes_wifi,
            dtn_bytes_sent_lte=self._bytes_lte,
            dtn_bundles_sent_wifi=self._bundles_wifi,
            dtn_bundles_sent_lte=self._bundles_lte,
            dtn_send_failures_wifi=self._failures_wifi,
            dtn_send_failures_lte=self._failures_lte,
            dtn_send_retries_wifi=self._retries_wifi,
            dtn_send_retries_lte=self._retries_lte,
        )
        try:
            maybe_awaitable = self._emit_send_counter(payload)
            if inspect.isawaitable(maybe_awaitable):
                asyncio.create_task(maybe_awaitable)
        except Exception as e:
            logger.debug("Failed to publish dtn_send_counter: %s", e)

    # ── AAP connection management ────────────────────────────────────────────

    def _ensure_connected_single(self) -> bool:
        """Open/reuse AAP connections to the default uD3TN socket."""
        try:
            if self._client_telem is None:
                self._client_telem = AAPv1Client(DTN_SOCKET_PATH)
                self._client_telem.connect()
                self._client_telem.register(DTN_AGENT_TELEM)

            if self._client_status is None:
                self._client_status = AAPv1Client(DTN_SOCKET_PATH)
                self._client_status.connect()
                self._client_status.register(DTN_AGENT_STATUS)

            return True
        except Exception as e:
            logger.error("DTN AAP (single) connect failed: %s", e)
            self._close_single_clients()
            return False

    def _ensure_connected_redundant(self) -> bool:
        """Open/reuse AAP connections to both WiFi and LTE uD3TN sockets."""
        try:
            if self._client_telem_wifi is None:
                self._client_telem_wifi = AAPv1Client(DTN_SOCKET_PATH_WIFI)
                self._client_telem_wifi.connect()
                self._client_telem_wifi.register(DTN_AGENT_TELEM)

            if self._client_status_wifi is None:
                self._client_status_wifi = AAPv1Client(DTN_SOCKET_PATH_WIFI)
                self._client_status_wifi.connect()
                self._client_status_wifi.register(DTN_AGENT_STATUS)
        except Exception as e:
            logger.error("DTN AAP (wifi) connect failed: %s", e)
            self._close_redundant_clients("wifi")

        try:
            if self._client_telem_lte is None:
                self._client_telem_lte = AAPv1Client(DTN_SOCKET_PATH_LTE)
                self._client_telem_lte.connect()
                self._client_telem_lte.register(DTN_AGENT_TELEM)

            if self._client_status_lte is None:
                self._client_status_lte = AAPv1Client(DTN_SOCKET_PATH_LTE)
                self._client_status_lte.connect()
                self._client_status_lte.register(DTN_AGENT_STATUS)
        except Exception as e:
            logger.error("DTN AAP (lte) connect failed: %s", e)
            self._close_redundant_clients("lte")

        # At least one side must be connected
        wifi_ok = self._client_telem_wifi is not None
        lte_ok  = self._client_telem_lte  is not None
        return wifi_ok or lte_ok

    def _close_single_clients(self) -> None:
        for client in (self._client_telem, self._client_status):
            if client:
                try:
                    client.close()
                except Exception:
                    pass
        self._client_telem  = None
        self._client_status = None

    def _close_redundant_clients(self, link: str) -> None:
        if link == "wifi":
            clients = [self._client_telem_wifi, self._client_status_wifi]
        else:
            clients = [self._client_telem_lte, self._client_status_lte]

        for c in clients:
            if c:
                try:
                    c.close()
                except Exception:
                    pass

        if link == "wifi":
            self._client_telem_wifi  = None
            self._client_status_wifi = None
        else:
            self._client_telem_lte  = None
            self._client_status_lte = None

    def _close_all_clients(self) -> None:
        self._close_single_clients()
        self._close_redundant_clients("wifi")
        self._close_redundant_clients("lte")

    def _record_retry(self, mode: str) -> None:
        if mode == "redundant":
            self._retries_wifi += 1
            self._retries_lte += 1
            return

        active_link = self._get_active_link()
        if active_link == "wifi":
            self._retries_wifi += 1
        elif active_link == "lte":
            self._retries_lte += 1
