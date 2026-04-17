"""
Canonical data models for all messages flowing through the Pi agent.
Shared between Pi services via import; mirrored in mac-backend/shared/schemas.py.
"""
from __future__ import annotations

import time
import uuid
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

from experiment import EXPERIMENT_MODES, new_experiment_session_id


# ── Experiment modes ──────────────────────────────────────────────────────────

class LinkScores(BaseModel):
    """Snapshot of adaptive link scores at send time (0.0–1.0, higher = better)."""
    wifi: Optional[float] = None
    lte:  Optional[float] = None


class AltitudeTelemetry(BaseModel):
    msg_type: Literal["altitude_telemetry"] = "altitude_telemetry"
    timestamp: float     = Field(default_factory=time.time,      description="Unix wall time")
    monotonic_ts: float  = Field(default_factory=time.monotonic, description="Monotonic clock for jitter analysis")
    sequence_number: int
    altitude: float                # metres above MSL (from GGA)
    fix_quality: int               # GGA field 6: 0=no-fix 1=GPS 2=DGPS 4=RTK-fixed 5=RTK-float
    fix_state: str                 # human label matching fix_quality
    num_satellites: int
    hdop: Optional[float] = None
    device_id: str
    node_id: str                   # DTN node ID of sender
    active_mode: str               # legacy field — mirrors experiment_mode
    active_link: str               # "wifi" | "lte" | "none"
    queue_depth: int               # queue depth at time of send attempt

    # ── Experiment metadata ───────────────────────────────────────────────────

    packet_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description=(
            "UUID identifying this logical packet. "
            "Both copies in redundant mode share the same packet_id, "
            "enabling the receiver to detect and discard the duplicate."
        ),
    )

    experiment_session_id: str = Field(
        default_factory=new_experiment_session_id,
        description="Per-run identifier rolled whenever the experiment mode changes.",
    )
    experiment_mode: str = "single_link_wifi"
    # "single_link_wifi" | "single_link_lte" | "adaptive" | "redundant"

    selected_link: str = "wifi"
    # Chosen policy output for the logical packet: "wifi" | "lte" | "both"

    decision_reason: str = "baseline"
    # "baseline" | "adaptive_score" | "adaptive_link_down" | "adaptive_hold" | "redundant"

    send_link: str = "wifi"
    # Which physical link THIS copy was sent over.
    # In redundant mode: copy A has send_link="wifi", copy B has send_link="lte".
    # In single/adaptive: equals active_link.

    send_monotonic: float = Field(
        default_factory=time.monotonic,
        description=(
            "Pi monotonic clock at the moment the bundle was handed to uD3TN. "
            "Use this (not timestamp) as the start time for end-to-end latency."
        ),
    )

    link_scores: Optional[LinkScores] = None
    # Snapshot of adaptive scores at send time.
    # Populated in adaptive mode; None in single_link / redundant.

    queue_depth_at_send: int = 0
    queue_wait_ms: float = 0.0
    # Optional: set by the Mac receiver when the bundle arrives (Pi leaves unset).
    receive_timestamp: Optional[float] = None


class GPSStatusMessage(BaseModel):
    msg_type: Literal["gps_status"] = "gps_status"
    timestamp: float    = Field(default_factory=time.time)
    monotonic_ts: float = Field(default_factory=time.monotonic)
    # Events: searching | no_fix | fix_found | serial_connected |
    #         serial_disconnected | parse_error | baudrate_changed
    event: str
    device_id: str
    node_id: str
    details:   Optional[str] = None
    baudrate:  Optional[int] = None
    fix_quality: Optional[int] = None


# Union used by QueueManager to type its contents
TelemetryMessage = Union[AltitudeTelemetry, GPSStatusMessage]


# ── Network emulation ─────────────────────────────────────────────────────────

class EmulationSettings(BaseModel):
    delay_ms:        int            = 0
    jitter_ms:       int            = 0
    loss_percent:    float          = 0.0   # 0.0–100.0
    bandwidth_kbps:  Optional[float]  = None  # None = unlimited
    outage:          bool           = False


# ── Management commands (Mac → Pi) ────────────────────────────────────────────

class SetModeCommand(BaseModel):
    """Legacy link-mode command — kept for backward compat."""
    cmd: Literal["set_mode"] = "set_mode"
    mode: Literal["wifi_only", "lte_only", "auto"]


class SetExperimentModeCommand(BaseModel):
    """Set the active experiment mode."""
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


class PingCommand(BaseModel):
    cmd: Literal["ping"] = "ping"


MgmtCommand = Union[
    SetModeCommand,
    SetExperimentModeCommand,
    SetEmulationCommand,
    RevertEmulationCommand,
    SetBaudrateCommand,
    SetGpsSendFrequencyCommand,
    ClearQueueCommand,
    SetLinkManagerConfigCommand,
    PingCommand,
]


# ── Status report (Pi → Mac, periodic) ───────────────────────────────────────

class PiStatusReport(BaseModel):
    msg_type: Literal["pi_status"] = "pi_status"
    timestamp: float = Field(default_factory=time.time)
    device_id: str

    # Interfaces
    wifi_interface: Optional[str]
    wifi_ip:        Optional[str]
    wifi_up:        bool
    wifi_reachable: bool

    lte_interface:  Optional[str]
    lte_ip:         Optional[str]
    lte_up:         bool
    lte_reachable:  bool

    eth_interface:  Optional[str]
    eth_ip:         Optional[str]
    eth_up:         bool

    # GPS
    gps_device:     Optional[str]
    gps_connected:  bool
    gps_fix_state:  str
    gps_baudrate:   int
    gps_send_frequency_hz: float

    # Queue
    queue_depth:    int
    queue_full:     bool
    queue_dropped:  int

    # Link / experiment mode
    active_mode:    str          # legacy; equals experiment_mode
    active_link:    str          # "wifi" | "lte" | "none"
    experiment_mode: str = "single_link_wifi"
    experiment_session_id: str = ""
    selected_link: str = "wifi"
    decision_reason: str = "baseline"
    last_failover_ts:        Optional[float]
    last_failover_direction: Optional[str]

    # Adaptive scoring (None when not in adaptive mode)
    wifi_score: Optional[float] = None
    lte_score:  Optional[float] = None
    wifi_ewma_rtt_ms: Optional[float] = None
    lte_ewma_rtt_ms:  Optional[float] = None
    wifi_probe_loss_rate: Optional[float] = None
    lte_probe_loss_rate:  Optional[float] = None
    probe_timeout_s: Optional[float] = None
    rtt_ceil_ms: Optional[float] = None

    # DTN counters (cumulative since start)
    dtn_bytes_sent_wifi:    int
    dtn_bytes_sent_lte:     int
    dtn_bundles_sent_wifi:  int
    dtn_bundles_sent_lte:   int
    dtn_send_failures_wifi: int = 0
    dtn_send_failures_lte:  int = 0
    dtn_send_retries_wifi:  int = 0
    dtn_send_retries_lte:   int = 0

    telemetry_generated: int = 0
    telemetry_enqueued:  int = 0

    # Active emulation settings
    emulation_wifi: Optional[EmulationSettings]
    emulation_lte:  Optional[EmulationSettings]


class DTNSendCounterMessage(BaseModel):
    """
    Per-send DTN counter update emitted immediately after a successful bundle send.
    """

    msg_type: Literal["dtn_send_counter"] = "dtn_send_counter"
    timestamp: float = Field(default_factory=time.time)
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
