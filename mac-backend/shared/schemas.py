"""
Shared Pydantic schemas for Mac backend services.
Mirrors pi-agent/schemas.py — keep in sync when adding fields.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class LinkScores(BaseModel):
    wifi: Optional[float] = None
    lte:  Optional[float] = None


class AltitudeTelemetry(BaseModel):
    msg_type: Literal["altitude_telemetry"] = "altitude_telemetry"
    timestamp:       float
    monotonic_ts:    float
    sequence_number: int
    altitude:        float
    fix_quality:     int
    fix_state:       str
    num_satellites:  int
    hdop:            Optional[float] = None
    device_id:       str
    node_id:         str
    active_mode:     str
    active_link:     str
    queue_depth:     int

    experiment_session_id: str = ""
    packet_id:        str = ""
    experiment_mode:  str = "single_link_wifi"
    selected_link:    str = "wifi"
    decision_reason:  str = "baseline"
    send_link:        str = "wifi"
    send_monotonic:   float = 0.0
    link_scores:      Optional[LinkScores] = None
    queue_depth_at_send: int = 0
    queue_wait_ms: float = 0.0
    # Wall time when the Mac received this bundle (for end-to-end transmit time in the UI).
    receive_timestamp: Optional[float] = None


class GPSStatusMessage(BaseModel):
    msg_type: Literal["gps_status"] = "gps_status"
    timestamp:   float
    monotonic_ts: float
    event:       str
    device_id:   str
    node_id:     str
    details:     Optional[str] = None
    baudrate:    Optional[int] = None
    fix_quality: Optional[int] = None


TelemetryMessage = Union[AltitudeTelemetry, GPSStatusMessage]


class EmulationSettings(BaseModel):
    delay_ms:       int           = 0
    jitter_ms:      int           = 0
    loss_percent:   float         = 0.0
    bandwidth_kbps: Optional[int] = None
    outage:         bool          = False


class PiStatusReport(BaseModel):
    msg_type: Literal["pi_status"] = "pi_status"
    timestamp: float

    device_id: str

    wifi_interface: Optional[str] = None
    wifi_ip:        Optional[str] = None
    wifi_up:        bool = False
    wifi_reachable: bool = False

    lte_interface:  Optional[str] = None
    lte_ip:         Optional[str] = None
    lte_up:         bool = False
    lte_reachable:  bool = False

    eth_interface:  Optional[str] = None
    eth_ip:         Optional[str] = None
    eth_up:         bool = False

    gps_device:     Optional[str] = None
    gps_connected:  bool = False
    gps_fix_state:  str = "unknown"
    gps_baudrate:   int = 0
    gps_send_frequency_hz: float = 1.0

    queue_depth:   int = 0
    queue_full:    bool = False
    queue_dropped: int = 0

    active_mode:             str = "single_link_wifi"
    active_link:             str = "none"
    experiment_mode:         str = "single_link_wifi"
    experiment_session_id:   str = ""
    selected_link:           str = "wifi"
    decision_reason:         str = "baseline"
    last_failover_ts:        Optional[float] = None
    last_failover_direction: Optional[str]   = None

    wifi_score:       Optional[float] = None
    lte_score:        Optional[float] = None
    wifi_ewma_rtt_ms: Optional[float] = None
    lte_ewma_rtt_ms:  Optional[float] = None
    wifi_probe_loss_rate: Optional[float] = None
    lte_probe_loss_rate:  Optional[float] = None
    probe_timeout_s: Optional[float] = None
    rtt_ceil_ms: Optional[float] = None

    dtn_bytes_sent_wifi:   int = 0
    dtn_bytes_sent_lte:    int = 0
    dtn_bundles_sent_wifi: int = 0
    dtn_bundles_sent_lte:  int = 0
    dtn_send_failures_wifi: int = 0
    dtn_send_failures_lte:  int = 0
    dtn_send_retries_wifi:  int = 0
    dtn_send_retries_lte:   int = 0

    telemetry_generated: int = 0
    telemetry_enqueued:  int = 0

    emulation_wifi: Optional[EmulationSettings] = None
    emulation_lte:  Optional[EmulationSettings] = None


class DTNSendCounterMessage(BaseModel):
    msg_type: Literal["dtn_send_counter"] = "dtn_send_counter"
    timestamp: float
    device_id: str
    link: Literal["wifi", "lte"]
    bundle_msg_type: Literal["altitude_telemetry", "gps_status"]
    sequence_number: Optional[int] = None
    packet_id: Optional[str] = None
    payload_bytes: int
    dtn_bytes_sent_wifi: int
    dtn_bytes_sent_lte: int
    dtn_bundles_sent_wifi: int
    dtn_bundles_sent_lte: int
    dtn_send_failures_wifi: int = 0
    dtn_send_failures_lte: int = 0
    dtn_send_retries_wifi: int = 0
    dtn_send_retries_lte: int = 0


class DTNCounters(BaseModel):
    """Physical DTN traffic counters."""
    bytes_sent_wifi:   int = 0
    bytes_sent_lte:    int = 0
    bundles_sent_wifi: int = 0
    bundles_sent_lte:  int = 0
    bytes_received:    int = 0
    bundles_received:  int = 0
    send_failures_wifi: int = 0
    send_failures_lte:  int = 0
    send_retries_wifi:  int = 0
    send_retries_lte:   int = 0


class TelemetryMetrics(BaseModel):
    deadline_ms: int
    window_size: int
    samples_received: int = 0
    packets_received: int = 0
    packets_expected: int = 0
    packets_missing:  int = 0
    packet_delivery_rate:   float = 100.0
    latest_latency_ms:      Optional[float] = None
    avg_latency_ms:         Optional[float] = None
    max_latency_ms:         Optional[float] = None
    deadline_success_rate:  float = 100.0
    deadline_success_count: int = 0
    deadline_miss_count:    int = 0


class FailoverEvent(BaseModel):
    timestamp: float
    direction: str


class Event(BaseModel):
    id:         int
    timestamp:  float
    event_type: str
    summary:    str
    detail:     Optional[str] = None
    link:       Optional[str] = None


class SwitchoverEvent(BaseModel):
    ts:                    float
    from_link:             str
    to_link:               str
    trigger:               str
    wifi_score_at_switch:  Optional[float] = None
    lte_score_at_switch:   Optional[float] = None
    wifi_ewma_rtt_ms:      Optional[float] = None
    lte_ewma_rtt_ms:       Optional[float] = None


class DuplicateEvent(BaseModel):
    ts:              float
    packet_id:       str
    winning_link:    str
    late_link:       str
    sequence_number: int
    duplicate_gap_ms: float = 0.0


class RecentTelemetryResult(BaseModel):
    ts:                 float
    experiment_session_id: str
    packet_id:          str
    sequence_number:    int
    experiment_mode:    str
    selected_link:      str
    winning_link:       str
    latency_ms:         float
    queue_wait_ms:      float
    queue_depth_at_send: int
    altitude:           float
    had_duplicate:      bool = False


class ExperimentMetrics(BaseModel):
    experiment_mode:  str
    experiment_session_id: str
    session_start_ts: float

    packets_generated: int = 0
    packets_enqueued: int = 0
    packets_unique_received: int = 0
    packets_queue_dropped: int = 0
    unique_delivery_rate: float = 100.0
    total_duplicates: int = 0

    avg_latency_ms:   Optional[float] = None
    p50_latency_ms:   Optional[float] = None
    p95_latency_ms:   Optional[float] = None
    max_latency_ms:   Optional[float] = None
    avg_queue_wait_ms: Optional[float] = None
    max_queue_wait_ms: Optional[float] = None
    latency_by_link:  Dict[str, float] = Field(default_factory=dict)

    current_queue_depth:   int = 0
    max_queue_depth_seen:  int = 0
    queue_overflow_count:  int = 0

    wifi_score_current:    Optional[float] = None
    lte_score_current:     Optional[float] = None
    wifi_ewma_rtt_ms:      Optional[float] = None
    lte_ewma_rtt_ms:       Optional[float] = None
    wifi_probe_loss_rate:  Optional[float] = None
    lte_probe_loss_rate:   Optional[float] = None
    switchover_count:      int = 0
    switchover_events:     List[SwitchoverEvent] = Field(default_factory=list)

    redundant_first_wifi:  int = 0
    redundant_first_lte:   int = 0
    redundant_single_path_only: int = 0
    duplicate_events:      List[DuplicateEvent] = Field(default_factory=list)


class ExperimentDistributionBucket(BaseModel):
    experiment_mode: str
    emulation_signature: str
    emulation_wifi: Optional[EmulationSettings] = None
    emulation_lte: Optional[EmulationSettings] = None
    session_count: int = 0
    mode_change_count: int = 0
    emulation_change_count: int = 0

    packets_generated: int = 0
    packets_enqueued: int = 0
    packets_unique_received: int = 0
    packets_queue_dropped: int = 0
    total_duplicates: int = 0
    unique_delivery_rate: float = 100.0

    avg_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    avg_queue_wait_ms: Optional[float] = None
    max_queue_wait_ms: Optional[float] = None


class ExperimentDistributionMetrics(BaseModel):
    updated_ts: float
    total_buckets: int = 0
    buckets: List[ExperimentDistributionBucket] = Field(default_factory=list)


class SetModeCommand(BaseModel):
    cmd: Literal["set_mode"] = "set_mode"
    mode: Literal["wifi_only", "lte_only", "auto"]


class SetExperimentModeCommand(BaseModel):
    cmd: Literal["set_experiment_mode"] = "set_experiment_mode"
    mode: Literal["single_link_wifi", "single_link_lte", "adaptive", "redundant"]


class SetEmulationCommand(BaseModel):
    cmd: Literal["set_emulation"] = "set_emulation"
    interface_role: Literal["wifi", "lte", "both"]
    settings: EmulationSettings


class RevertEmulationCommand(BaseModel):
    cmd: Literal["revert_emulation"] = "revert_emulation"
    interface_role: Literal["wifi", "lte", "both"]


class SetBaudrateCommand(BaseModel):
    cmd: Literal["set_baudrate"] = "set_baudrate"
    baudrate: int


class SetGpsSendFrequencyCommand(BaseModel):
    cmd: Literal["set_gps_send_frequency"] = "set_gps_send_frequency"
    hz: float


class ClearQueueCommand(BaseModel):
    cmd: Literal["clear_queue"] = "clear_queue"


class SetLinkManagerConfigCommand(BaseModel):
    cmd: Literal["set_link_manager_config"] = "set_link_manager_config"
    probe_timeout_s: Optional[float] = None
    rtt_ceil_ms: Optional[float] = None
    restart_agent: bool = True


class RecordedSessionSummary(BaseModel):
    """Aggregates for one experiment_session_id (matches frontend SessionSummaryRow)."""

    sessionId: str
    mode: str
    packetCount: int
    duplicateCount: int
    avgLatencyMs: Optional[float] = None
    p95LatencyMs: Optional[float] = None
    avgQueueWaitMs: Optional[float] = None
    latestTs: float


class ExperimentRecordingRunCreate(BaseModel):
    experiment_session_id: str
    stopped_at_ms: int
    summary: RecordedSessionSummary
    rows: List[RecentTelemetryResult]
    metrics_snapshot: Optional[ExperimentMetrics] = None
    deadline_snapshot: Optional[TelemetryMetrics] = None


class ExperimentRecordingRunOut(BaseModel):
    """Serialized to JSON with camelCase keys (matches frontend CachedExperimentRecordingRun)."""

    id: str
    stoppedAtMs: int
    sessionId: str
    summary: RecordedSessionSummary
    rows: List[RecentTelemetryResult]
    metricsSnapshot: Optional[ExperimentMetrics] = None
    deadlineSnapshot: Optional[TelemetryMetrics] = None
