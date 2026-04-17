import React from 'react';
import { formatBytes, formatMs, formatPercent } from '../../lib/format';
import {
  DTNCounters,
  EXPERIMENT_MODE_LABELS,
  ExperimentMetrics,
  PiStatusReport,
  TelemetryMetrics,
} from '../../types';

interface OperationsOverviewProps {
  connectionState: 'connecting' | 'open' | 'closed';
  counters: DTNCounters | null;
  experimentMetrics: ExperimentMetrics | null;
  metrics: TelemetryMetrics | null;
  status: PiStatusReport | null;
}

interface MetricCardProps {
  eyebrow: string;
  value: string;
  detail: string;
  tone?: 'good' | 'warn' | 'bad';
}

function MetricCard({ eyebrow, value, detail, tone }: MetricCardProps) {
  return (
    <article className={`metric-card ${tone ? `metric-${tone}` : ''}`}>
      <p>{eyebrow}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

export function OperationsOverview({
  connectionState,
  counters,
  experimentMetrics,
  metrics,
  status,
}: OperationsOverviewProps) {
  const totalSentBytes =
    (counters?.bytes_sent_wifi ?? 0) + (counters?.bytes_sent_lte ?? 0);
  const totalBundles =
    (counters?.bundles_sent_wifi ?? 0) + (counters?.bundles_sent_lte ?? 0);

  return (
    <section className="metrics-grid">
      <MetricCard
        eyebrow="Realtime channel"
        value={connectionState === 'open' ? 'Online' : 'Degraded'}
        detail={
          connectionState === 'open'
            ? 'WebSocket updates are flowing from the backend.'
            : 'UI is relying on the last successful snapshot.'
        }
        tone={connectionState === 'open' ? 'good' : 'warn'}
      />

      <MetricCard
        eyebrow="Experiment mode"
        value={
          status ? EXPERIMENT_MODE_LABELS[status.experiment_mode] : 'Unknown'
        }
        detail={`Active link: ${status?.active_link?.toUpperCase() ?? '—'} • decision ${status?.decision_reason ?? '—'}`}
        tone={
          status?.active_link === 'wifi'
            ? 'good'
            : status?.active_link === 'lte'
            ? 'warn'
            : 'bad'
        }
      />

      <MetricCard
        eyebrow="Queue pressure"
        value={status ? `${status.queue_depth} / 1024` : 'Unavailable'}
        detail={
          status?.queue_full
            ? `${status.queue_dropped} telemetry samples dropped`
            : 'Queue operating inside safe headroom'
        }
        tone={status?.queue_full ? 'bad' : 'good'}
      />

      <MetricCard
        eyebrow="DTN throughput"
        value={counters ? formatBytes(totalSentBytes) : 'Unavailable'}
        detail={
          counters
            ? `${totalBundles} bundles sent, ${counters.bundles_received} bundles received`
            : 'Waiting for DTN counters'
        }
      />

      <MetricCard
        eyebrow="Unique delivery"
        value={
          experimentMetrics
            ? formatPercent(experimentMetrics.unique_delivery_rate)
            : 'Unavailable'
        }
        detail={
          experimentMetrics
            ? `${experimentMetrics.packets_unique_received}/${experimentMetrics.packets_enqueued || 0} accepted logical packets`
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

      <MetricCard
        eyebrow="Deadline success"
        value={metrics ? formatPercent(metrics.deadline_success_rate) : 'Unavailable'}
        detail={
          metrics
            ? `Target ${metrics.deadline_ms} ms, ${metrics.deadline_success_count} hits`
            : 'Waiting for realtime latency data'
        }
        tone={
          metrics && metrics.deadline_success_rate >= 95
            ? 'good'
            : metrics && metrics.deadline_success_rate >= 75
            ? 'warn'
            : 'bad'
        }
      />

      <MetricCard
        eyebrow={status?.experiment_mode === 'redundant' ? 'Duplicates' : 'Switchovers'}
        value={
          experimentMetrics
            ? status?.experiment_mode === 'redundant'
              ? `${experimentMetrics.total_duplicates}`
              : `${experimentMetrics.switchover_count}`
            : 'Unavailable'
        }
        detail={
          experimentMetrics
            ? status?.experiment_mode === 'redundant'
              ? `WiFi first ${experimentMetrics.redundant_first_wifi}, LTE first ${experimentMetrics.redundant_first_lte}`
              : `Latency ${formatMs(experimentMetrics.avg_latency_ms, 0)} avg, queue wait ${formatMs(experimentMetrics.avg_queue_wait_ms, 0)}`
            : 'Waiting for experiment metrics'
        }
      />
    </section>
  );
}
