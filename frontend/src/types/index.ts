export interface EmulationSettings {
  delay_ms: number;
  jitter_ms: number;
  loss_percent: number;
  bandwidth_kbps: number | null;
  outage: boolean;
}

export type ExperimentMode =
  | 'single_link_wifi'
  | 'single_link_lte'
  | 'adaptive'
  | 'redundant';

export type LinkMode = 'wifi_only' | 'lte_only' | 'auto';
export type InterfaceRole = 'wifi' | 'lte' | 'both';

export const EXPERIMENT_MODE_LABELS: Record<ExperimentMode, string> = {
  single_link_wifi: 'Single Link (WiFi)',
  single_link_lte: 'Single Link (LTE)',
  adaptive: 'Adaptive Selection',
  redundant: 'Redundant Transmission',
};

export interface PiStatusReport {
  msg_type: 'pi_status';
  timestamp: number;
  device_id: string;

  wifi_interface: string | null;
  wifi_ip: string | null;
  wifi_up: boolean;
  wifi_reachable: boolean;

  lte_interface: string | null;
  lte_ip: string | null;
  lte_up: boolean;
  lte_reachable: boolean;

  eth_interface: string | null;
  eth_ip: string | null;
  eth_up: boolean;

  gps_device: string | null;
  gps_connected: boolean;
  gps_fix_state: string;
  gps_baudrate: number;
  gps_send_frequency_hz: number;

  queue_depth: number;
  queue_full: boolean;
  queue_dropped: number;

  active_mode: string;
  active_link: 'wifi' | 'lte' | 'none';
  experiment_mode: ExperimentMode;
  experiment_session_id: string;
  selected_link: 'wifi' | 'lte' | 'both';
  decision_reason: string;
  last_failover_ts: number | null;
  last_failover_direction: string | null;

  wifi_score: number | null;
  lte_score: number | null;
  wifi_ewma_rtt_ms: number | null;
  lte_ewma_rtt_ms: number | null;
  wifi_probe_loss_rate: number | null;
  lte_probe_loss_rate: number | null;

  dtn_bytes_sent_wifi: number;
  dtn_bytes_sent_lte: number;
  dtn_bundles_sent_wifi: number;
  dtn_bundles_sent_lte: number;
  dtn_send_failures_wifi: number;
  dtn_send_failures_lte: number;
  dtn_send_retries_wifi: number;
  dtn_send_retries_lte: number;

  telemetry_generated: number;
  telemetry_enqueued: number;

  emulation_wifi: EmulationSettings | null;
  emulation_lte: EmulationSettings | null;
}

export interface LinkScores {
  wifi: number | null;
  lte: number | null;
}

export interface AltitudeTelemetry {
  msg_type: 'altitude_telemetry';
  timestamp: number;
  receive_timestamp?: number | null;
  payload_size_bytes?: number | null;
  monotonic_ts: number;
  sequence_number: number;
  altitude: number;
  fix_quality: number;
  fix_state: string;
  num_satellites: number;
  hdop: number | null;
  device_id: string;
  node_id: string;
  active_mode: string;
  active_link: string;
  queue_depth: number;
  experiment_session_id: string;
  packet_id: string;
  experiment_mode: ExperimentMode;
  selected_link: 'wifi' | 'lte' | 'both';
  decision_reason: string;
  send_link: string;
  send_monotonic: number;
  link_scores: LinkScores | null;
  queue_depth_at_send: number;
  queue_wait_ms: number;
}

export interface GPSStatusMessage {
  msg_type: 'gps_status';
  timestamp: number;
  monotonic_ts: number;
  event: string;
  device_id: string;
  node_id: string;
  details: string | null;
  baudrate: number | null;
  fix_quality: number | null;
}

export type TelemetryMessage = AltitudeTelemetry | GPSStatusMessage;

export interface DTNCounters {
  bytes_sent_wifi: number;
  bytes_sent_lte: number;
  bundles_sent_wifi: number;
  bundles_sent_lte: number;
  bytes_received: number;
  bundles_received: number;
  send_failures_wifi: number;
  send_failures_lte: number;
  send_retries_wifi: number;
  send_retries_lte: number;
}

export interface TelemetryMetrics {
  deadline_ms: number;
  window_size: number;
  samples_received: number;
  packets_received: number;
  packets_expected: number;
  packets_missing: number;
  packet_delivery_rate: number;
  latest_latency_ms: number | null;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
  deadline_success_rate: number;
  deadline_success_count: number;
  deadline_miss_count: number;
}

export interface Event {
  id: number;
  timestamp: number;
  event_type:
    | 'telemetry'
    | 'gps_status'
    | 'failover'
    | 'queue_warning'
    | 'switchover'
    | 'duplicate'
    | 'mode_change'
    | 'emulation_change';
  summary: string;
  detail: string | null;
  link: string | null;
}

/** One row in the connectivity feed: Pi periodic status (mgmt heartbeat path). */
export interface PiStatusHeartbeatEntry {
  id: number;
  /** Pi status snapshot timestamp (seconds, from device). */
  deviceTimestamp: number;
  /** When the dashboard received this frame (ms). */
  receivedAt: number;
  summary: string;
  detail: string | null;
}

export interface SwitchoverEvent {
  ts: number;
  from_link: string;
  to_link: string;
  trigger: string;
  wifi_score_at_switch: number | null;
  lte_score_at_switch: number | null;
  wifi_ewma_rtt_ms: number | null;
  lte_ewma_rtt_ms: number | null;
}

export interface DuplicateEvent {
  ts: number;
  packet_id: string;
  winning_link: string;
  late_link: string;
  sequence_number: number;
  duplicate_gap_ms: number;
}

export interface RecentTelemetryResult {
  ts: number;
  experiment_session_id: string;
  packet_id: string;
  sequence_number: number;
  experiment_mode: ExperimentMode;
  selected_link: 'wifi' | 'lte' | 'both';
  winning_link: string;
  latency_ms: number;
  queue_wait_ms: number;
  queue_depth_at_send: number;
  altitude: number;
  had_duplicate: boolean;
}

export interface ExperimentMetrics {
  experiment_mode: ExperimentMode;
  experiment_session_id: string;
  session_start_ts: number;

  packets_generated: number;
  packets_enqueued: number;
  packets_unique_received: number;
  packets_queue_dropped: number;
  unique_delivery_rate: number;
  total_duplicates: number;

  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  max_latency_ms: number | null;
  avg_queue_wait_ms: number | null;
  max_queue_wait_ms: number | null;
  latency_by_link: Record<string, number>;

  current_queue_depth: number;
  max_queue_depth_seen: number;
  queue_overflow_count: number;

  wifi_score_current: number | null;
  lte_score_current: number | null;
  wifi_ewma_rtt_ms: number | null;
  lte_ewma_rtt_ms: number | null;
  wifi_probe_loss_rate: number | null;
  lte_probe_loss_rate: number | null;
  switchover_count: number;
  switchover_events: SwitchoverEvent[];

  redundant_first_wifi: number;
  redundant_first_lte: number;
  redundant_single_path_only: number;
  duplicate_events: DuplicateEvent[];
}

/** Aggregates for one experiment_session_id (emulation results table + SQLite runs). */
export interface RecordedSessionSummary {
  sessionId: string;
  mode: ExperimentMode;
  packetCount: number;
  duplicateCount: number;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
  avgQueueWaitMs: number | null;
  latestTs: number;
}

/** One persisted recording stop, loaded from `experiment_recording_runs` in the Mac backend DB. */
export interface CachedExperimentRecordingRun {
  id: string;
  stoppedAtMs: number;
  sessionId: string;
  summary: RecordedSessionSummary;
  rows: RecentTelemetryResult[];
  metricsSnapshot: ExperimentMetrics | null;
  deadlineSnapshot: TelemetryMetrics | null;
}

export interface ExperimentRecordingRunPayload {
  experiment_session_id: string;
  stopped_at_ms: number;
  summary: RecordedSessionSummary;
  rows: RecentTelemetryResult[];
  metrics_snapshot: ExperimentMetrics | null;
  deadline_snapshot: TelemetryMetrics | null;
}

export interface ExperimentDistributionBucket {
  experiment_mode: ExperimentMode;
  emulation_signature: string;
  emulation_wifi: EmulationSettings | null;
  emulation_lte: EmulationSettings | null;
  session_count: number;
  mode_change_count: number;
  emulation_change_count: number;
  packets_generated: number;
  packets_enqueued: number;
  packets_unique_received: number;
  packets_queue_dropped: number;
  total_duplicates: number;
  unique_delivery_rate: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_queue_wait_ms: number | null;
  max_queue_wait_ms: number | null;
}

export interface ExperimentDistributionMetrics {
  updated_ts: number;
  total_buckets: number;
  buckets: ExperimentDistributionBucket[];
}

export interface SetExperimentModeCommand {
  cmd: 'set_experiment_mode';
  mode: ExperimentMode;
}

export interface SetModeCommand {
  cmd: 'set_mode';
  mode: LinkMode;
}

export interface SetEmulationCommand {
  cmd: 'set_emulation';
  interface_role: InterfaceRole;
  settings: EmulationSettings;
}

export interface RevertEmulationCommand {
  cmd: 'revert_emulation';
  interface_role: InterfaceRole;
}

export interface SetBaudrateCommand {
  cmd: 'set_baudrate';
  baudrate: number;
}

export interface SetGpsSendFrequencyCommand {
  cmd: 'set_gps_send_frequency';
  hz: number;
}

export interface ClearQueueCommand {
  cmd: 'clear_queue';
}

export type MgmtCommand =
  | SetExperimentModeCommand
  | SetModeCommand
  | SetEmulationCommand
  | RevertEmulationCommand
  | SetBaudrateCommand
  | SetGpsSendFrequencyCommand
  | ClearQueueCommand;

export type WSMessage =
  | { type: 'pi_status'; data: PiStatusReport }
  | { type: 'dtn_counters'; data: DTNCounters }
  | { type: 'metrics'; data: TelemetryMetrics }
  | { type: 'experiment_metrics'; data: ExperimentMetrics }
  | { type: 'experiment_distribution'; data: ExperimentDistributionMetrics }
  | { type: 'telemetry_result'; data: RecentTelemetryResult }
  | { type: 'event'; data: Event }
  | { type: 'bundle'; data: TelemetryMessage };
