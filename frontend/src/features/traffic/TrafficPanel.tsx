import React from 'react';
import { Panel } from '../../components/Panel';
import { formatBytes, formatMs, formatPercent } from '../../lib/format';
import {
  DTNCounters,
  ExperimentMetrics,
  PiStatusReport,
  TelemetryMetrics,
} from '../../types';

interface TrafficPanelProps {
  counters: DTNCounters | null;
  experimentMetrics: ExperimentMetrics | null;
  metrics: TelemetryMetrics | null;
  status: PiStatusReport | null;
}

interface StatProps {
  label: string;
  value: string;
  note?: string;
  tone?: 'good' | 'warn' | 'bad';
}

function Stat({ label, value, note, tone }: StatProps) {
  return (
    <div className={`stat-row ${tone ? `stat-${tone}` : ''}`}>
      <div>
        <span>{label}</span>
        {note && <p>{note}</p>}
      </div>
      <strong>{value}</strong>
    </div>
  );
}

export function TrafficPanel({
  counters,
  experimentMetrics,
  metrics,
  status,
}: TrafficPanelProps) {
  return (
    <Panel title="DTN Traffic" className="traffic-panel">
      {status?.queue_full && (
        <div className="banner banner-danger">
          Queue is full and telemetry is paused. Dropped samples: {status.queue_dropped}.
        </div>
      )}

      <div className="stat-section">
        <h3>Queue behavior</h3>
        <Stat
          label="Depth"
          value={status ? `${status.queue_depth} / 1024` : 'Unavailable'}
          note="Current queue occupancy reported by the Pi."
          tone={status?.queue_full ? 'bad' : 'good'}
        />
        <Stat
          label="Queue wait"
          value={formatMs(experimentMetrics?.avg_queue_wait_ms, 0)}
          note={
            experimentMetrics?.max_queue_wait_ms != null
              ? `Peak ${formatMs(experimentMetrics.max_queue_wait_ms, 0)}`
              : 'Waiting for accepted packets'
          }
        />
      </div>

      <div className="stat-section">
        <h3>Per-link DTN traffic and health</h3>
        <Stat
          label="WiFi"
          value={
            counters
              ? `${formatBytes(counters.bytes_sent_wifi)} • ${counters.bundles_sent_wifi} bundles`
              : 'Unavailable'
          }
          note={
            status
              ? `${
                  status.wifi_reachable ? 'Reachable' : status.wifi_up ? 'Up' : 'Down'
                } • score ${status.wifi_score?.toFixed(2) ?? '—'} • RTT ${formatMs(status.wifi_ewma_rtt_ms, 0)} • loss ${
                  status.wifi_probe_loss_rate != null
                    ? formatPercent(status.wifi_probe_loss_rate * 100)
                    : '—'
                }${
                  counters
                    ? ` • retries ${counters.send_retries_wifi} • failures ${counters.send_failures_wifi}`
                    : ''
                }`
              : undefined
          }
          tone={status?.wifi_reachable ? 'good' : status?.wifi_up ? 'warn' : 'bad'}
        />
        <Stat
          label="LTE"
          value={
            counters
              ? `${formatBytes(counters.bytes_sent_lte)} • ${counters.bundles_sent_lte} bundles`
              : 'Unavailable'
          }
          note={
            status
              ? `${
                  status.lte_reachable ? 'Reachable' : status.lte_up ? 'Up' : 'Down'
                } • score ${status.lte_score?.toFixed(2) ?? '—'} • RTT ${formatMs(status.lte_ewma_rtt_ms, 0)} • loss ${
                  status.lte_probe_loss_rate != null
                    ? formatPercent(status.lte_probe_loss_rate * 100)
                    : '—'
                }${
                  counters
                    ? ` • retries ${counters.send_retries_lte} • failures ${counters.send_failures_lte}`
                    : ''
                }`
              : undefined
          }
          tone={status?.lte_reachable ? 'good' : status?.lte_up ? 'warn' : 'bad'}
        />
      </div>

      <div className="stat-section">
        <h3>Mac-side outcomes</h3>
        <Stat
          label="Physical ingress"
          value={
            counters
              ? `${formatBytes(counters.bytes_received)} • ${counters.bundles_received} bundles`
              : 'Unavailable'
          }
        />
        <Stat
          label="Unique delivery"
          value={
            experimentMetrics
              ? formatPercent(experimentMetrics.unique_delivery_rate)
              : 'Unavailable'
          }
          note={
            experimentMetrics
              ? `${experimentMetrics.packets_unique_received}/${experimentMetrics.packets_enqueued || 0} logical packets`
              : 'Waiting for experiment metrics'
          }
          tone={
            experimentMetrics && experimentMetrics.unique_delivery_rate >= 95
              ? 'good'
              : experimentMetrics && experimentMetrics.unique_delivery_rate >= 75
              ? 'warn'
              : 'bad'
          }
        />
        <Stat
          label="Realtime latency"
          value={
            experimentMetrics?.avg_latency_ms != null
              ? `${formatMs(experimentMetrics.avg_latency_ms, 0)} avg`
              : 'Unavailable'
          }
          note={
            experimentMetrics?.p95_latency_ms != null
              ? `p95 ${formatMs(experimentMetrics.p95_latency_ms, 0)} • max ${formatMs(experimentMetrics.max_latency_ms, 0)}`
              : metrics
              ? `Deadline success ${formatPercent(metrics.deadline_success_rate)}`
              : 'Waiting for enough samples'
          }
        />
      </div>
    </Panel>
  );
}
