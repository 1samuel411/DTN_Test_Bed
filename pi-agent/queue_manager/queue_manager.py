"""
Bounded telemetry queue with backpressure.

Policy:
  • Altitude telemetry obeys the 1024-message cap.
  • GPS status events bypass the cap (they are infrequent and critical).
  • When the cap is hit:
      - log a WARNING
      - stop accepting telemetry (set accepting_telemetry = False)
      - drop subsequent telemetry silently (count dropped)
  • Resume accepting when depth falls below 90 % of max (hysteresis).
  • Operator can force-clear via clear().
"""

import asyncio
import logging

from schemas import GPSStatusMessage, TelemetryMessage

logger = logging.getLogger(__name__)

_RESUME_FRACTION = 0.90   # resume collecting when depth < 90 % of max


class QueueManager:
    def __init__(self, max_size: int = 1024) -> None:
        self._max_size     = max_size
        self._resume_at    = int(max_size * _RESUME_FRACTION)
        self._q: asyncio.Queue[TelemetryMessage] = asyncio.Queue()

        self._accepting    = True      # False once queue fills
        self._full_warned  = False     # avoids spam
        self._dropped      = 0
        self._total_in     = 0

    # ── Public properties ────────────────────────────────────────────────────

    @property
    def depth(self) -> int:
        return self._q.qsize()

    @property
    def is_full(self) -> bool:
        return self._q.qsize() >= self._max_size

    @property
    def accepting_telemetry(self) -> bool:
        return self._accepting

    @property
    def dropped_count(self) -> int:
        return self._dropped

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def put_nowait(self, msg: TelemetryMessage) -> bool:
        """
        Attempt to enqueue a message.

        Returns True if accepted, False if dropped.
        GPS status messages always accepted.
        Altitude telemetry respects the size cap.
        """
        is_status = isinstance(msg, GPSStatusMessage)

        if not is_status:
            if not self._accepting:
                self._dropped += 1
                # Log every 100 drops to avoid flood
                if self._dropped % 100 == 1:
                    logger.warning(
                        "QUEUE FULL: telemetry dropped (total dropped=%d, depth=%d/%d)",
                        self._dropped, self._q.qsize(), self._max_size,
                    )
                return False

            if self._q.qsize() >= self._max_size:
                if not self._full_warned:
                    logger.warning(
                        "QUEUE FULL at %d messages. Stopping telemetry collection. "
                        "Will resume when depth < %d. (dropped so far: %d)",
                        self._max_size, self._resume_at, self._dropped,
                    )
                    self._full_warned = True
                self._accepting = False
                self._dropped += 1
                return False

        self._q.put_nowait(msg)
        self._total_in += 1
        self._maybe_resume_collection()

        return True

    # ── Dequeue ──────────────────────────────────────────────────────────────

    async def get(self) -> TelemetryMessage:
        """Block until a message is available."""
        msg = await self._q.get()
        self._maybe_resume_collection()
        return msg

    def task_done(self) -> None:
        self._q.task_done()

    # ── Management ───────────────────────────────────────────────────────────

    def clear(self) -> int:
        """Drain the entire queue. Returns number of messages cleared."""
        count = 0
        while not self._q.empty():
            try:
                self._q.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        self._accepting   = True
        self._full_warned = False
        logger.info("Queue cleared by operator: removed %d messages", count)
        return count

    def stats(self) -> dict:
        return {
            "depth":               self._q.qsize(),
            "max_size":            self._max_size,
            "is_full":             self.is_full,
            "accepting_telemetry": self._accepting,
            "total_enqueued":      self._total_in,
            "dropped_count":       self._dropped,
        }

    def _maybe_resume_collection(self) -> None:
        if not self._accepting and self._q.qsize() < self._resume_at:
            logger.info(
                "Queue depth %d < resume threshold %d. Resuming telemetry collection.",
                self._q.qsize(), self._resume_at,
            )
            self._accepting = True
            self._full_warned = False
