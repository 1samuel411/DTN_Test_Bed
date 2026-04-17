"""
Shared in-memory + SQLite store for Mac backend.

Experiment metrics in this store are logical per-run results.
DTN counters remain physical traffic counters.
"""

import json
import logging
import os
import sqlite3
import statistics
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .schemas import (
    AltitudeTelemetry,
    DTNCounters,
    DTNSendCounterMessage,
    DuplicateEvent,
    Event,
    ExperimentDistributionBucket,
    ExperimentDistributionMetrics,
    ExperimentMetrics,
    EmulationSettings,
    ExperimentRecordingRunCreate,
    ExperimentRecordingRunOut,
    GPSStatusMessage,
    PiStatusReport,
    RecentTelemetryResult,
    RecordedSessionSummary,
    SwitchoverEvent,
    TelemetryMetrics,
    TelemetryMessage,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".run", "dtn_testbed.db")
)

_MEM_WINDOW = 1000
_MAX_SW_EVENTS = 50
_MAX_DUP_EVENTS = 50


@dataclass
class _MetricSample:
    sequence_number: int
    latency_ms: float
    queue_wait_ms: float
    deadline_met: bool
    send_link: str = "unknown"


@dataclass
class _DedupEntry:
    winning_link: str
    first_rx_ts: float
    expires_at: float


@dataclass
class _ExperimentState:
    mode: str
    session_id: str = ""
    start_ts: float = field(default_factory=time.time)
    enqueued_baseline: int = 0

    unique_received: int = 0
    total_duplicates: int = 0
    queue_overflow_count: int = 0
    max_queue_depth: int = 0

    latency_by_link: Dict[str, List[float]] = field(
        default_factory=lambda: {"wifi": [], "lte": [], "unknown": []}
    )
    switchover_events: List[SwitchoverEvent] = field(default_factory=list)
    first_wifi: int = 0
    first_lte: int = 0
    duplicate_events: List[DuplicateEvent] = field(default_factory=list)


@dataclass
class _DistributionBucketState:
    experiment_mode: str
    emulation_signature: str
    emulation_wifi: Optional[EmulationSettings]
    emulation_lte: Optional[EmulationSettings]
    session_count: int = 0
    mode_change_count: int = 0
    emulation_change_count: int = 0

    packets_generated: int = 0
    packets_enqueued: int = 0
    packets_unique_received: int = 0
    packets_queue_dropped: int = 0
    total_duplicates: int = 0

    latency_samples: List[float] = field(default_factory=list)
    queue_wait_samples: List[float] = field(default_factory=list)


class Store:
    """
    Thread-safe shared store.
    All public methods are safe to call from any thread or coroutine.
    """

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        realtime_deadline_ms: int = 2000,
        metrics_window_size: int = 100,
        dedup_ttl_s: int = 3600,
    ) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None
        self._deadline_ms = realtime_deadline_ms
        self._metrics_window_size = metrics_window_size
        self._dedup_ttl_s = dedup_ttl_s

        self._pi_status: Optional[PiStatusReport] = None
        self._dtn_counters = DTNCounters()
        self._telemetry_metrics = TelemetryMetrics(
            deadline_ms=realtime_deadline_ms,
            window_size=metrics_window_size,
        )
        self._last_event_id = 0

        self._recent_telemetry: deque[AltitudeTelemetry] = deque(maxlen=_MEM_WINDOW)
        self._recent_results: deque[RecentTelemetryResult] = deque(maxlen=_MEM_WINDOW)
        self._recent_events: deque[Event] = deque(maxlen=_MEM_WINDOW)
        self._metric_samples: deque[_MetricSample] = deque(maxlen=metrics_window_size)

        self._dedup_seen: Dict[Tuple[str, str], _DedupEntry] = {}
        self._exp: _ExperimentState = _ExperimentState(mode="single_link_wifi")
        self._distribution_buckets: Dict[Tuple[str, str], _DistributionBucketState] = {}
        self._active_distribution_key: Optional[Tuple[str, str]] = None

        self._ws_broadcast: Optional[Callable] = None

    @staticmethod
    def _copy_emulation_settings(
        settings: Optional[EmulationSettings],
    ) -> Optional[EmulationSettings]:
        if settings is None:
            return None
        return settings.model_copy(deep=True)

    @staticmethod
    def _format_emulation_signature(settings: Optional[EmulationSettings]) -> str:
        if settings is None:
            return "none"
        bandwidth = (
            "unlimited"
            if settings.bandwidth_kbps is None
            else str(settings.bandwidth_kbps)
        )
        return (
            f"d{settings.delay_ms}"
            f"-j{settings.jitter_ms}"
            f"-l{settings.loss_percent:.2f}"
            f"-b{bandwidth}"
            f"-o{1 if settings.outage else 0}"
        )

    def _build_emulation_signature(self, status: Optional[PiStatusReport]) -> str:
        if status is None:
            return "wifi:none|lte:none"
        wifi_sig = self._format_emulation_signature(status.emulation_wifi)
        lte_sig = self._format_emulation_signature(status.emulation_lte)
        return f"wifi:{wifi_sig}|lte:{lte_sig}"

    def _get_or_create_distribution_bucket(
        self,
        mode: str,
        signature: str,
        emulation_wifi: Optional[EmulationSettings],
        emulation_lte: Optional[EmulationSettings],
    ) -> _DistributionBucketState:
        key = (mode, signature)
        bucket = self._distribution_buckets.get(key)
        if bucket is not None:
            return bucket

        bucket = _DistributionBucketState(
            experiment_mode=mode,
            emulation_signature=signature,
            emulation_wifi=self._copy_emulation_settings(emulation_wifi),
            emulation_lte=self._copy_emulation_settings(emulation_lte),
        )
        self._distribution_buckets[key] = bucket
        return bucket

    def _active_distribution_bucket(
        self,
    ) -> Optional[_DistributionBucketState]:
        if self._active_distribution_key is None:
            return None
        return self._distribution_buckets.get(self._active_distribution_key)

    def open(self) -> None:
        db_dir = os.path.dirname(os.path.abspath(self._db_path))
        if db_dir:
            os.makedirs(db_dir, mode=0o755, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_schema()
        logger.info("Store opened: %s", self._db_path)

    def close(self) -> None:
        if self._db:
            self._db.close()

    def set_ws_broadcast(self, cb: Callable) -> None:
        self._ws_broadcast = cb

    def _broadcast(self, payload: dict) -> None:
        if self._ws_broadcast:
            try:
                self._ws_broadcast(payload)
            except Exception as e:
                logger.debug("WS broadcast error: %s", e)

    def update_pi_status(self, status: PiStatusReport) -> None:
        with self._lock:
            old = self._pi_status
            self._pi_status = status

            self._dtn_counters.bytes_sent_wifi = status.dtn_bytes_sent_wifi
            self._dtn_counters.bytes_sent_lte = status.dtn_bytes_sent_lte
            self._dtn_counters.bundles_sent_wifi = status.dtn_bundles_sent_wifi
            self._dtn_counters.bundles_sent_lte = status.dtn_bundles_sent_lte
            self._dtn_counters.send_failures_wifi = status.dtn_send_failures_wifi
            self._dtn_counters.send_failures_lte = status.dtn_send_failures_lte
            self._dtn_counters.send_retries_wifi = status.dtn_send_retries_wifi
            self._dtn_counters.send_retries_lte = status.dtn_send_retries_lte

            new_mode = status.experiment_mode or status.active_mode
            old_mode = (old.experiment_mode or old.active_mode) if old else None
            is_first_status = old is None
            emulation_signature = self._build_emulation_signature(status)
            old_emulation_signature = self._build_emulation_signature(old) if old else None
            dist_bucket = self._get_or_create_distribution_bucket(
                new_mode,
                emulation_signature,
                status.emulation_wifi,
                status.emulation_lte,
            )
            self._active_distribution_key = (new_mode, emulation_signature)

            if old:
                dist_bucket.packets_generated += max(
                    0,
                    status.telemetry_generated - old.telemetry_generated,
                )
                dist_bucket.packets_enqueued += max(
                    0,
                    status.telemetry_enqueued - old.telemetry_enqueued,
                )
                dist_bucket.packets_queue_dropped += max(
                    0,
                    status.queue_dropped - old.queue_dropped,
                )

            new_session = status.experiment_session_id or ""
            if (
                is_first_status
                or new_mode != self._exp.mode
                or (new_session and new_session != self._exp.session_id)
            ):
                logger.info(
                    "Experiment context changed: mode=%s session=%s",
                    new_mode, new_session,
                )
                self._exp = _ExperimentState(
                    mode=new_mode,
                    session_id=new_session,
                    enqueued_baseline=max(0, status.telemetry_enqueued),
                )
                self._dedup_seen.clear()
                self._metric_samples.clear()
                self._recent_results.clear()
                self._telemetry_metrics = TelemetryMetrics(
                    deadline_ms=self._deadline_ms,
                    window_size=self._metrics_window_size,
                )
                dist_bucket.session_count += 1
                if old and old_mode != new_mode:
                    dist_bucket.mode_change_count += 1
                self._add_event("mode_change", f"Experiment mode → {new_mode}", link=None)
            elif self._exp.enqueued_baseline == 0 and status.telemetry_enqueued > 0:
                # Backfill baseline once counters start flowing for older sessions.
                self._exp.enqueued_baseline = status.telemetry_enqueued

            if old and old_emulation_signature != emulation_signature:
                dist_bucket.emulation_change_count += 1
                self._add_event(
                    "emulation_change",
                    "Emulation profile updated",
                    detail=f"{old_emulation_signature} → {emulation_signature}",
                    link=None,
                )

            if (
                old
                and old.experiment_session_id == status.experiment_session_id
                and old.active_link in ("wifi", "lte")
                and status.active_link in ("wifi", "lte")
                and old.active_link != status.active_link
            ):
                trigger = status.decision_reason or "adaptive_score"
                sw_event = SwitchoverEvent(
                    ts=time.time(),
                    from_link=old.active_link,
                    to_link=status.active_link,
                    trigger=trigger,
                    wifi_score_at_switch=status.wifi_score,
                    lte_score_at_switch=status.lte_score,
                    wifi_ewma_rtt_ms=status.wifi_ewma_rtt_ms,
                    lte_ewma_rtt_ms=status.lte_ewma_rtt_ms,
                )
                self._exp.switchover_events.append(sw_event)
                if len(self._exp.switchover_events) > _MAX_SW_EVENTS:
                    self._exp.switchover_events.pop(0)
                self._add_event(
                    "switchover",
                    f"Link: {old.active_link}→{status.active_link} ({trigger})",
                    link=status.active_link,
                    detail=(
                        f"wifi_score={status.wifi_score} lte_score={status.lte_score} "
                        f"wifi_rtt={status.wifi_ewma_rtt_ms} lte_rtt={status.lte_ewma_rtt_ms}"
                    ),
                )

            if status.queue_depth > self._exp.max_queue_depth:
                self._exp.max_queue_depth = status.queue_depth
            if old and not old.queue_full and status.queue_full:
                self._exp.queue_overflow_count += 1
                self._add_event("queue_warning", "Queue FULL (1024 messages)", None)

            counters_payload = self._dtn_counters.model_dump()
            metrics_payload = self._telemetry_metrics.model_dump()
            exp_payload = self._build_experiment_metrics(status).model_dump()
            distribution_payload = self._build_experiment_distribution_metrics().model_dump()

        self._broadcast({"type": "dtn_counters", "data": counters_payload})
        self._broadcast({"type": "metrics", "data": metrics_payload})
        self._broadcast({"type": "pi_status", "data": status.model_dump()})
        self._broadcast({"type": "experiment_metrics", "data": exp_payload})
        self._broadcast({"type": "experiment_distribution", "data": distribution_payload})

    def get_pi_status(self) -> Optional[PiStatusReport]:
        with self._lock:
            return self._pi_status

    def ingest_dtn_send_counter(self, msg: DTNSendCounterMessage) -> None:
        """
        Apply per-send DTN counter updates pushed by the Pi management channel.
        """
        with self._lock:
            self._dtn_counters.bytes_sent_wifi = max(
                self._dtn_counters.bytes_sent_wifi,
                msg.dtn_bytes_sent_wifi,
            )
            self._dtn_counters.bytes_sent_lte = max(
                self._dtn_counters.bytes_sent_lte,
                msg.dtn_bytes_sent_lte,
            )
            self._dtn_counters.bundles_sent_wifi = max(
                self._dtn_counters.bundles_sent_wifi,
                msg.dtn_bundles_sent_wifi,
            )
            self._dtn_counters.bundles_sent_lte = max(
                self._dtn_counters.bundles_sent_lte,
                msg.dtn_bundles_sent_lte,
            )
            self._dtn_counters.send_failures_wifi = max(
                self._dtn_counters.send_failures_wifi,
                msg.dtn_send_failures_wifi,
            )
            self._dtn_counters.send_failures_lte = max(
                self._dtn_counters.send_failures_lte,
                msg.dtn_send_failures_lte,
            )
            self._dtn_counters.send_retries_wifi = max(
                self._dtn_counters.send_retries_wifi,
                msg.dtn_send_retries_wifi,
            )
            self._dtn_counters.send_retries_lte = max(
                self._dtn_counters.send_retries_lte,
                msg.dtn_send_retries_lte,
            )
            counters_payload = self._dtn_counters.model_dump()

        self._broadcast({"type": "dtn_counters", "data": counters_payload})

    def ingest_bundle(self, msg: TelemetryMessage, raw_size: int) -> bool:
        is_duplicate = False
        counters_payload = None
        metrics_payload = None
        exp_payload = None
        distribution_payload = None
        result_payload = None
        bundle_payload = None

        with self._lock:
            self._prune_dedup_entries()

            if isinstance(msg, AltitudeTelemetry):
                now = time.time()
                key = (msg.experiment_session_id or "", msg.packet_id or "")

                if key[0] and key[1] and key in self._dedup_seen:
                    entry = self._dedup_seen[key]
                    late_link = msg.send_link or msg.active_link or "unknown"
                    duplicate_gap_ms = max(0.0, (now - entry.first_rx_ts) * 1000.0)
                    self._exp.total_duplicates += 1

                    dup_event = DuplicateEvent(
                        ts=now,
                        packet_id=msg.packet_id,
                        winning_link=entry.winning_link,
                        late_link=late_link,
                        sequence_number=msg.sequence_number,
                        duplicate_gap_ms=duplicate_gap_ms,
                    )
                    self._exp.duplicate_events.append(dup_event)
                    if len(self._exp.duplicate_events) > _MAX_DUP_EVENTS:
                        self._exp.duplicate_events.pop(0)

                    updated = self._mark_recent_result_duplicate(msg.experiment_session_id, msg.packet_id)
                    if updated:
                        result_payload = updated.model_dump()

                    self._add_event(
                        "duplicate",
                        f"Duplicate discarded: {entry.winning_link} beat {late_link}",
                        link=late_link,
                        detail=f"seq={msg.sequence_number} gap={duplicate_gap_ms:.1f} ms",
                    )
                    self._dtn_counters.bytes_received += raw_size
                    self._dtn_counters.bundles_received += 1
                    is_duplicate = True
                    active_bucket = self._active_distribution_bucket()
                    if active_bucket:
                        active_bucket.total_duplicates += 1
                    counters_payload = self._dtn_counters.model_dump()
                    exp_payload = self._build_experiment_metrics(self._pi_status).model_dump()
                    distribution_payload = self._build_experiment_distribution_metrics().model_dump()
                else:
                    winning_link = msg.send_link or msg.active_link or "unknown"
                    if key[0] and key[1]:
                        self._dedup_seen[key] = _DedupEntry(
                            winning_link=winning_link,
                            first_rx_ts=now,
                            expires_at=now + self._dedup_ttl_s,
                        )

                    if msg.experiment_mode == "redundant":
                        if winning_link == "wifi":
                            self._exp.first_wifi += 1
                        elif winning_link == "lte":
                            self._exp.first_lte += 1

                    self._exp.unique_received += 1
                    self._dtn_counters.bytes_received += raw_size
                    self._dtn_counters.bundles_received += 1

                    latency_ms = max(0.0, (now - msg.timestamp) * 1000.0)
                    active_bucket = self._active_distribution_bucket()
                    if active_bucket:
                        active_bucket.packets_unique_received += 1
                        active_bucket.latency_samples.append(latency_ms)
                        active_bucket.queue_wait_samples.append(msg.queue_wait_ms)

                    self._metric_samples.append(
                        _MetricSample(
                            sequence_number=msg.sequence_number,
                            latency_ms=latency_ms,
                            queue_wait_ms=msg.queue_wait_ms,
                            deadline_met=latency_ms <= self._deadline_ms,
                            send_link=winning_link,
                        )
                    )
                    self._recompute_metrics()

                    link_samples = self._exp.latency_by_link.setdefault(winning_link, [])
                    link_samples.append(latency_ms)
                    if len(link_samples) > self._metrics_window_size:
                        link_samples.pop(0)

                    result = RecentTelemetryResult(
                        ts=now,
                        experiment_session_id=msg.experiment_session_id,
                        packet_id=msg.packet_id,
                        sequence_number=msg.sequence_number,
                        experiment_mode=msg.experiment_mode,
                        selected_link=msg.selected_link,
                        winning_link=winning_link,
                        latency_ms=latency_ms,
                        queue_wait_ms=msg.queue_wait_ms,
                        queue_depth_at_send=msg.queue_depth_at_send,
                        altitude=msg.altitude,
                    )
                    self._recent_results.append(result)
                    result_payload = result.model_dump()

                    msg_received = msg.model_copy(update={"receive_timestamp": now})
                    self._recent_telemetry.append(msg_received)
                    self._add_event(
                        "telemetry",
                        f"alt={msg.altitude:.1f}m mode={msg.experiment_mode} win={winning_link}",
                        link=winning_link,
                    )
                    self._persist_telemetry(msg_received)

                    counters_payload = self._dtn_counters.model_dump()
                    metrics_payload = self._telemetry_metrics.model_dump()
                    exp_payload = self._build_experiment_metrics(self._pi_status).model_dump()
                    distribution_payload = self._build_experiment_distribution_metrics().model_dump()
                    bundle_payload = msg_received.model_dump()

            elif isinstance(msg, GPSStatusMessage):
                self._dtn_counters.bytes_received += raw_size
                self._dtn_counters.bundles_received += 1
                self._add_event("gps_status", f"GPS: {msg.event}", detail=msg.details)
                self._persist_status_event(msg)

                counters_payload = self._dtn_counters.model_dump()
                metrics_payload = self._telemetry_metrics.model_dump()
                exp_payload = self._build_experiment_metrics(self._pi_status).model_dump()
                distribution_payload = self._build_experiment_distribution_metrics().model_dump()
                bundle_payload = msg.model_dump()

        if counters_payload:
            self._broadcast({"type": "dtn_counters", "data": counters_payload})
        if exp_payload:
            self._broadcast({"type": "experiment_metrics", "data": exp_payload})
        if distribution_payload:
            self._broadcast({"type": "experiment_distribution", "data": distribution_payload})
        if result_payload:
            self._broadcast({"type": "telemetry_result", "data": result_payload})

        if not is_duplicate:
            if metrics_payload:
                self._broadcast({"type": "metrics", "data": metrics_payload})
            if bundle_payload:
                msg_type = "bundle"
                self._broadcast({"type": msg_type, "data": bundle_payload})

        return not is_duplicate

    def get_recent_telemetry(self, limit: int = 50) -> List[AltitudeTelemetry]:
        with self._lock:
            items = list(self._recent_telemetry)
        return items[-limit:]

    def get_recent_results(self, limit: int = 50) -> List[RecentTelemetryResult]:
        with self._lock:
            items = list(self._recent_results)
        return items[-limit:]

    def save_experiment_recording_run(self, payload: ExperimentRecordingRunCreate) -> str:
        run_id = str(uuid.uuid4())
        metrics_json = (
            json.dumps(payload.metrics_snapshot.model_dump())
            if payload.metrics_snapshot
            else None
        )
        deadline_json = (
            json.dumps(payload.deadline_snapshot.model_dump())
            if payload.deadline_snapshot
            else None
        )
        with self._lock:
            if not self._db:
                raise RuntimeError("Store DB not open")
            self._db.execute(
                """
                INSERT INTO experiment_recording_runs (
                    id, experiment_session_id, stopped_at_ms, summary_json, rows_json, metrics_json, deadline_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    payload.experiment_session_id,
                    payload.stopped_at_ms,
                    json.dumps(payload.summary.model_dump()),
                    json.dumps([r.model_dump() for r in payload.rows]),
                    metrics_json,
                    deadline_json,
                ),
            )
            self._db.commit()
        return run_id

    def list_experiment_recording_runs(self, limit: int = 20) -> List[ExperimentRecordingRunOut]:
        with self._lock:
            if not self._db:
                return []
            cur = self._db.execute(
                """
                SELECT id, experiment_session_id, stopped_at_ms, summary_json, rows_json, metrics_json, deadline_json
                FROM experiment_recording_runs
                ORDER BY stopped_at_ms DESC
                LIMIT ?
                """,
                (limit,),
            )
            raw_rows = cur.fetchall()

        out: List[ExperimentRecordingRunOut] = []
        for row in raw_rows:
            summary = RecordedSessionSummary.model_validate(json.loads(row["summary_json"]))
            result_rows = [
                RecentTelemetryResult.model_validate(x) for x in json.loads(row["rows_json"])
            ]
            metrics = (
                ExperimentMetrics.model_validate(json.loads(row["metrics_json"]))
                if row["metrics_json"]
                else None
            )
            deadline = (
                TelemetryMetrics.model_validate(json.loads(row["deadline_json"]))
                if row["deadline_json"]
                else None
            )
            out.append(
                ExperimentRecordingRunOut(
                    id=row["id"],
                    stoppedAtMs=row["stopped_at_ms"],
                    sessionId=row["experiment_session_id"],
                    summary=summary,
                    rows=result_rows,
                    metricsSnapshot=metrics,
                    deadlineSnapshot=deadline,
                )
            )
        return out

    def get_recent_events(self, limit: int = 100) -> List[Event]:
        with self._lock:
            items = list(self._recent_events)
        return items[-limit:]

    def get_dtn_counters(self) -> DTNCounters:
        with self._lock:
            return self._dtn_counters.model_copy()

    def get_telemetry_metrics(self) -> TelemetryMetrics:
        with self._lock:
            return self._telemetry_metrics.model_copy()

    def get_experiment_metrics(self) -> ExperimentMetrics:
        with self._lock:
            return self._build_experiment_metrics(self._pi_status)

    def get_experiment_distribution_metrics(self) -> ExperimentDistributionMetrics:
        with self._lock:
            return self._build_experiment_distribution_metrics()

    def _build_experiment_distribution_metrics(self) -> ExperimentDistributionMetrics:
        buckets: List[ExperimentDistributionBucket] = []

        for bucket in sorted(
            self._distribution_buckets.values(),
            key=lambda row: (
                row.experiment_mode,
                row.emulation_signature,
            ),
        ):
            latency_samples = bucket.latency_samples[-self._metrics_window_size :]
            queue_wait_samples = bucket.queue_wait_samples[-self._metrics_window_size :]
            sorted_latencies = sorted(latency_samples)
            unique_delivery_rate = 100.0
            if bucket.packets_enqueued > 0:
                unique_delivery_rate = min(
                    100.0,
                    (bucket.packets_unique_received / bucket.packets_enqueued) * 100.0,
                )

            p95_latency = None
            if len(sorted_latencies) >= 20:
                p95_latency = sorted_latencies[int((len(sorted_latencies) - 1) * 0.95)]

            buckets.append(
                ExperimentDistributionBucket(
                    experiment_mode=bucket.experiment_mode,
                    emulation_signature=bucket.emulation_signature,
                    emulation_wifi=self._copy_emulation_settings(bucket.emulation_wifi),
                    emulation_lte=self._copy_emulation_settings(bucket.emulation_lte),
                    session_count=bucket.session_count,
                    mode_change_count=bucket.mode_change_count,
                    emulation_change_count=bucket.emulation_change_count,
                    packets_generated=bucket.packets_generated,
                    packets_enqueued=bucket.packets_enqueued,
                    packets_unique_received=bucket.packets_unique_received,
                    packets_queue_dropped=bucket.packets_queue_dropped,
                    total_duplicates=bucket.total_duplicates,
                    unique_delivery_rate=unique_delivery_rate,
                    avg_latency_ms=statistics.mean(latency_samples) if latency_samples else None,
                    p95_latency_ms=p95_latency,
                    avg_queue_wait_ms=statistics.mean(queue_wait_samples) if queue_wait_samples else None,
                    max_queue_wait_ms=max(queue_wait_samples) if queue_wait_samples else None,
                )
            )

        return ExperimentDistributionMetrics(
            updated_ts=time.time(),
            total_buckets=len(buckets),
            buckets=buckets,
        )

    def _build_experiment_metrics(self, status: Optional[PiStatusReport]) -> ExperimentMetrics:
        exp = self._exp
        all_latencies = [s.latency_ms for s in self._metric_samples]
        all_queue_waits = [s.queue_wait_ms for s in self._metric_samples]
        avg_lat = statistics.mean(all_latencies) if all_latencies else None
        max_lat = max(all_latencies) if all_latencies else None
        p50_lat = statistics.median(all_latencies) if all_latencies else None
        p95_lat = (
            sorted(all_latencies)[int((len(all_latencies) - 1) * 0.95)]
            if len(all_latencies) >= 20 else None
        )

        latency_by_link = {
            link: statistics.mean(values)
            for link, values in exp.latency_by_link.items()
            if values
        }

        packets_generated = status.telemetry_generated if status else 0
        total_enqueued = status.telemetry_enqueued if status else 0
        packets_enqueued = max(0, total_enqueued - exp.enqueued_baseline)
        packets_queue_dropped = status.queue_dropped if status else 0
        unique_delivery_rate = 100.0
        if packets_enqueued > 0:
            unique_delivery_rate = min(100.0, (exp.unique_received / packets_enqueued) * 100.0)

        return ExperimentMetrics(
            experiment_mode=exp.mode,
            experiment_session_id=exp.session_id,
            session_start_ts=exp.start_ts,
            packets_generated=packets_generated,
            packets_enqueued=packets_enqueued,
            packets_unique_received=exp.unique_received,
            packets_queue_dropped=packets_queue_dropped,
            unique_delivery_rate=unique_delivery_rate,
            total_duplicates=exp.total_duplicates,
            avg_latency_ms=avg_lat,
            p50_latency_ms=p50_lat,
            p95_latency_ms=p95_lat,
            max_latency_ms=max_lat,
            avg_queue_wait_ms=statistics.mean(all_queue_waits) if all_queue_waits else None,
            max_queue_wait_ms=max(all_queue_waits) if all_queue_waits else None,
            latency_by_link=latency_by_link,
            current_queue_depth=status.queue_depth if status else 0,
            max_queue_depth_seen=exp.max_queue_depth,
            queue_overflow_count=exp.queue_overflow_count,
            wifi_score_current=status.wifi_score if status else None,
            lte_score_current=status.lte_score if status else None,
            wifi_ewma_rtt_ms=status.wifi_ewma_rtt_ms if status else None,
            lte_ewma_rtt_ms=status.lte_ewma_rtt_ms if status else None,
            wifi_probe_loss_rate=status.wifi_probe_loss_rate if status else None,
            lte_probe_loss_rate=status.lte_probe_loss_rate if status else None,
            switchover_count=len(exp.switchover_events),
            switchover_events=list(exp.switchover_events[-_MAX_SW_EVENTS:]),
            redundant_first_wifi=exp.first_wifi,
            redundant_first_lte=exp.first_lte,
            redundant_single_path_only=max(0, exp.unique_received - exp.total_duplicates),
            duplicate_events=list(exp.duplicate_events[-_MAX_DUP_EVENTS:]),
        )

    def _add_event(
        self,
        event_type: str,
        summary: str,
        detail: Optional[str] = None,
        link: Optional[str] = None,
    ) -> None:
        self._last_event_id += 1
        ev = Event(
            id=self._last_event_id,
            timestamp=time.time(),
            event_type=event_type,
            summary=summary,
            detail=detail,
            link=link,
        )
        self._recent_events.append(ev)
        self._broadcast({"type": "event", "data": ev.model_dump()})

    def _recompute_metrics(self) -> None:
        if not self._metric_samples:
            self._telemetry_metrics = TelemetryMetrics(
                deadline_ms=self._deadline_ms,
                window_size=self._metrics_window_size,
            )
            return

        samples = list(self._metric_samples)
        unique_sequences = {sample.sequence_number for sample in samples}
        min_seq = min(unique_sequences)
        max_seq = max(unique_sequences)
        expected_packets = max_seq - min_seq + 1
        received_packets = len(unique_sequences)
        missing_packets = max(expected_packets - received_packets, 0)
        latencies = [sample.latency_ms for sample in samples]
        deadline_success_count = sum(1 for s in samples if s.deadline_met)
        deadline_miss_count = len(samples) - deadline_success_count

        self._telemetry_metrics = TelemetryMetrics(
            deadline_ms=self._deadline_ms,
            window_size=self._metrics_window_size,
            samples_received=len(samples),
            packets_received=received_packets,
            packets_expected=expected_packets,
            packets_missing=missing_packets,
            packet_delivery_rate=(
                (received_packets / expected_packets) * 100.0 if expected_packets else 100.0
            ),
            latest_latency_ms=latencies[-1],
            avg_latency_ms=sum(latencies) / len(latencies),
            max_latency_ms=max(latencies),
            deadline_success_rate=(
                (deadline_success_count / len(samples)) * 100.0 if samples else 100.0
            ),
            deadline_success_count=deadline_success_count,
            deadline_miss_count=deadline_miss_count,
        )

    def _prune_dedup_entries(self) -> None:
        now = time.time()
        expired = [key for key, entry in self._dedup_seen.items() if entry.expires_at <= now]
        for key in expired:
            self._dedup_seen.pop(key, None)

    def _mark_recent_result_duplicate(
        self, experiment_session_id: str, packet_id: str
    ) -> Optional[RecentTelemetryResult]:
        for idx in range(len(self._recent_results) - 1, -1, -1):
            result = self._recent_results[idx]
            if (
                result.experiment_session_id == experiment_session_id
                and result.packet_id == packet_id
            ):
                updated = result.model_copy(update={"had_duplicate": True})
                self._recent_results[idx] = updated
                return updated
        return None

    def _init_schema(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                monotonic_ts REAL,
                sequence_number INTEGER,
                altitude REAL,
                fix_quality INTEGER,
                fix_state TEXT,
                num_satellites INTEGER,
                hdop REAL,
                device_id TEXT,
                active_mode TEXT,
                active_link TEXT,
                queue_depth INTEGER,
                experiment_session_id TEXT,
                packet_id TEXT,
                experiment_mode TEXT,
                selected_link TEXT,
                decision_reason TEXT,
                send_link TEXT,
                queue_depth_at_send INTEGER,
                queue_wait_ms REAL
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS gps_status_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                event TEXT,
                device_id TEXT,
                details TEXT,
                baudrate INTEGER,
                fix_quality INTEGER
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS experiment_recording_runs (
                id TEXT PRIMARY KEY NOT NULL,
                experiment_session_id TEXT NOT NULL,
                stopped_at_ms INTEGER NOT NULL,
                summary_json TEXT NOT NULL,
                rows_json TEXT NOT NULL,
                metrics_json TEXT,
                deadline_json TEXT
            )
            """
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_experiment_recording_runs_stopped "
            "ON experiment_recording_runs (stopped_at_ms DESC)"
        )
        self._ensure_column("telemetry", "experiment_session_id", "TEXT")
        self._ensure_column("telemetry", "selected_link", "TEXT")
        self._ensure_column("telemetry", "decision_reason", "TEXT")
        self._ensure_column("telemetry", "queue_depth_at_send", "INTEGER")
        self._ensure_column("telemetry", "queue_wait_ms", "REAL")
        self._ensure_column("telemetry", "receive_timestamp", "REAL")
        self._db.commit()

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        cursor = self._db.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
        if column not in existing:
            self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _persist_telemetry(self, msg: AltitudeTelemetry) -> None:
        try:
            self._db.execute(
                """
                INSERT INTO telemetry (
                    timestamp, monotonic_ts, sequence_number, altitude, fix_quality,
                    fix_state, num_satellites, hdop, device_id, active_mode, active_link,
                    queue_depth, experiment_session_id, packet_id, experiment_mode,
                    selected_link, decision_reason, send_link, queue_depth_at_send, queue_wait_ms,
                    receive_timestamp
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    msg.timestamp,
                    msg.monotonic_ts,
                    msg.sequence_number,
                    msg.altitude,
                    msg.fix_quality,
                    msg.fix_state,
                    msg.num_satellites,
                    msg.hdop,
                    msg.device_id,
                    msg.active_mode,
                    msg.active_link,
                    msg.queue_depth,
                    msg.experiment_session_id,
                    msg.packet_id,
                    msg.experiment_mode,
                    msg.selected_link,
                    msg.decision_reason,
                    msg.send_link,
                    msg.queue_depth_at_send,
                    msg.queue_wait_ms,
                    msg.receive_timestamp,
                ),
            )
            self._db.commit()
        except Exception as e:
            logger.error("SQLite persist telemetry error: %s", e)

    def _persist_status_event(self, msg: GPSStatusMessage) -> None:
        try:
            self._db.execute(
                """INSERT INTO gps_status_events VALUES (NULL,?,?,?,?,?,?)""",
                (
                    msg.timestamp,
                    msg.event,
                    msg.device_id,
                    msg.details,
                    msg.baudrate,
                    msg.fix_quality,
                ),
            )
            self._db.commit()
        except Exception as e:
            logger.error("SQLite persist status event error: %s", e)
