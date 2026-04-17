import React, { useMemo } from 'react';
import { Panel } from '../../components/Panel';
import { formatBytes, formatMs, formatPercent } from '../../lib/format';
import {
  AltitudeTelemetry,
  DTNCounters,
  ExperimentDistributionMetrics,
  ExperimentMetrics,
  EXPERIMENT_MODE_LABELS,
  PiStatusReport,
  TelemetryMetrics,
} from '../../types';

interface NetworkAnalyticsPanelProps {
  counters: DTNCounters | null;
  deadlineMetrics: TelemetryMetrics | null;
  distribution: ExperimentDistributionMetrics | null;
  metrics: ExperimentMetrics | null;
  status: PiStatusReport | null;
  telemetry: AltitudeTelemetry[];
}

function renderDistributionRows(distribution: ExperimentDistributionMetrics | null) {
  if (!distribution || distribution.buckets.length === 0) {
    return <p className="empty-state">Collecting distribution rows as mode and emulation settings change.</p>;
  }

  const buckets = [...distribution.buckets].sort((left, right) => {
    if (right.packets_enqueued !== left.packets_enqueued) {
      return right.packets_enqueued - left.packets_enqueued;
    }
    return right.session_count - left.session_count;
  });

  return (
    <div className="experiment-summary-table experiment-summary-table--distribution">
      <div className="experiment-summary-table__head experiment-summary-table__head--distribution">
        <span>Mode</span>
        <span>Sessions</span>
        <span>Enqueued</span>
        <span>Unique delivery</span>
        <span>Latency avg / p95</span>
        <span>Queue wait avg / max</span>
      </div>
      {buckets.map((bucket) => (
        <div
          key={`${bucket.experiment_mode}-${bucket.emulation_signature}`}
          className="experiment-summary-table__row experiment-summary-table__row--distribution"
        >
          <strong>{EXPERIMENT_MODE_LABELS[bucket.experiment_mode]}</strong>
          <span>{bucket.session_count}</span>
          <span>{bucket.packets_enqueued}</span>
          <span>{formatPercent(bucket.unique_delivery_rate)}</span>
          <span>
            {formatMs(bucket.avg_latency_ms, 0)} / {formatMs(bucket.p95_latency_ms, 0)}
          </span>
          <span>
            {formatMs(bucket.avg_queue_wait_ms, 0)} / {formatMs(bucket.max_queue_wait_ms, 0)}
          </span>
        </div>
      ))}
    </div>
  );
}

function buildLinkComparisonMatrix(
  counters: DTNCounters | null,
  deadlineMetrics: TelemetryMetrics | null,
  experimentMetrics: ExperimentMetrics | null,
  status: PiStatusReport | null,
  telemetry: AltitudeTelemetry[],
) {
  const deadlineMs = deadlineMetrics?.deadline_ms ?? null;
  const wifiSentBundles = counters?.bundles_sent_wifi ?? status?.dtn_bundles_sent_wifi ?? 0;
  const lteSentBundles = counters?.bundles_sent_lte ?? status?.dtn_bundles_sent_lte ?? 0;
  const wifiSentBytes = counters?.bytes_sent_wifi ?? status?.dtn_bytes_sent_wifi ?? 0;
  const lteSentBytes = counters?.bytes_sent_lte ?? status?.dtn_bytes_sent_lte ?? 0;
  const uniqueDelivered = experimentMetrics?.packets_unique_received ?? 0;

  const stats = telemetry.reduce(
    (current, sample) => {
      const rawLink = (sample.send_link || sample.active_link || '').toLowerCase();
      if (rawLink !== 'wifi' && rawLink !== 'lte') {
        return current;
      }

      const bucket = current[rawLink];
      bucket.received += 1;

      if (sample.receive_timestamp == null) {
        return current;
      }

      const latencyMs = Math.max(0, (sample.receive_timestamp - sample.timestamp) * 1000);
      bucket.latencyCount += 1;
      bucket.latencySumMs += latencyMs;

      if (deadlineMs != null) {
        bucket.deadlineChecks += 1;
        if (latencyMs > deadlineMs) {
          bucket.deadlineMisses += 1;
        }
      }

      return current;
    },
    {
      wifi: { received: 0, latencyCount: 0, latencySumMs: 0, deadlineChecks: 0, deadlineMisses: 0 },
      lte: { received: 0, latencyCount: 0, latencySumMs: 0, deadlineChecks: 0, deadlineMisses: 0 },
    },
  );

  const switchoverBreakdown = { wifi: 0, lte: 0 };
  (experimentMetrics?.switchover_events ?? []).forEach((event) => {
    const target = (event.to_link || '').toLowerCase();
    if (target === 'wifi' || target === 'lte') {
      switchoverBreakdown[target] += 1;
    }
  });

  const sessionMinutes = (() => {
    if (!experimentMetrics?.session_start_ts) {
      return null;
    }
    const referenceTs = status?.timestamp ?? Date.now() / 1000;
    const elapsedSeconds = Math.max(1, referenceTs - experimentMetrics.session_start_ts);
    return elapsedSeconds / 60;
  })();

  const wifiAvgLatency =
    stats.wifi.latencyCount > 0
      ? stats.wifi.latencySumMs / stats.wifi.latencyCount
      : experimentMetrics?.latency_by_link?.wifi ?? null;
  const lteAvgLatency =
    stats.lte.latencyCount > 0
      ? stats.lte.latencySumMs / stats.lte.latencyCount
      : experimentMetrics?.latency_by_link?.lte ?? null;

  const wifiPdr = wifiSentBundles > 0 ? (stats.wifi.received / wifiSentBundles) * 100 : null;
  const ltePdr = lteSentBundles > 0 ? (stats.lte.received / lteSentBundles) * 100 : null;

  // When a realtime deadline is configured but a link has no latency samples yet (or no traffic on that path),
  // treat miss rate as 0% so the row stays consistent with aggregate metrics instead of showing "Unavailable".
  const wifiDeadlineMissRate: number | null =
    deadlineMs == null
      ? null
      : stats.wifi.deadlineChecks > 0
        ? (stats.wifi.deadlineMisses / stats.wifi.deadlineChecks) * 100
        : 0;
  const lteDeadlineMissRate: number | null =
    deadlineMs == null
      ? null
      : stats.lte.deadlineChecks > 0
        ? (stats.lte.deadlineMisses / stats.lte.deadlineChecks) * 100
        : 0;

  const wifiSwitchPerMinute =
    sessionMinutes && sessionMinutes > 0 ? switchoverBreakdown.wifi / sessionMinutes : null;
  const lteSwitchPerMinute =
    sessionMinutes && sessionMinutes > 0 ? switchoverBreakdown.lte / sessionMinutes : null;

  const wifiOverhead =
    uniqueDelivered > 0 ? Math.max(0, ((wifiSentBundles - uniqueDelivered) / uniqueDelivered) * 100) : null;
  const lteOverhead =
    uniqueDelivered > 0 ? Math.max(0, ((lteSentBundles - uniqueDelivered) / uniqueDelivered) * 100) : null;

  return {
    deadlineMs,
    stats,
    wifiAvgLatency,
    lteAvgLatency,
    wifiPdr,
    ltePdr,
    wifiDeadlineMissRate,
    lteDeadlineMissRate,
    switchoverBreakdown,
    wifiSwitchPerMinute,
    lteSwitchPerMinute,
    wifiOverhead,
    lteOverhead,
    wifiSentBundles,
    lteSentBundles,
    wifiSentBytes,
    lteSentBytes,
  };
}

export function NetworkAnalyticsPanel({
  counters,
  deadlineMetrics,
  distribution,
  metrics,
  status,
  telemetry,
}: NetworkAnalyticsPanelProps) {
  const matrix = useMemo(
    () => buildLinkComparisonMatrix(counters, deadlineMetrics, metrics, status, telemetry),
    [counters, deadlineMetrics, metrics, status, telemetry],
  );

  return (
    <Panel title="Network Analytics" className="traffic-panel">
      <div className="stat-section">
        <h3>Network performance matrix (WiFi vs LTE)</h3>
        <div className="network-performance-table">
          <div className="network-performance-table__header">
            <span>Metric</span>
            <span>Definition</span>
            <span>WiFi</span>
            <span>LTE</span>
          </div>

          <div className="network-performance-table__row">
            <span>End-to-End Latency</span>
            <span>Time for a telemetry packet to reach the server.</span>
            <strong>
              {matrix.wifiAvgLatency != null
                ? `${formatMs(matrix.wifiAvgLatency, 0)} avg (${matrix.stats.wifi.latencyCount} samples)`
                : 'Unavailable'}
            </strong>
            <strong>
              {matrix.lteAvgLatency != null
                ? `${formatMs(matrix.lteAvgLatency, 0)} avg (${matrix.stats.lte.latencyCount} samples)`
                : 'Unavailable'}
            </strong>
          </div>

          <div className="network-performance-table__row">
            <span>Packet Delivery Ratio</span>
            <span>Fraction of transmitted packets successfully received.</span>
            <strong>
              {matrix.wifiPdr != null
                ? `${formatPercent(Math.min(100, matrix.wifiPdr))} (${matrix.stats.wifi.received}/${matrix.wifiSentBundles})`
                : 'Unavailable'}
            </strong>
            <strong>
              {matrix.ltePdr != null
                ? `${formatPercent(Math.min(100, matrix.ltePdr))} (${matrix.stats.lte.received}/${matrix.lteSentBundles})`
                : 'Unavailable'}
            </strong>
          </div>

          <div className="network-performance-table__row">
            <span>Deadline Miss Rate</span>
            <span>Percentage of packets arriving too late for real-time use.</span>
            <strong>
              {matrix.wifiDeadlineMissRate != null
                ? `${formatPercent(matrix.wifiDeadlineMissRate)} (${matrix.stats.wifi.deadlineMisses}/${matrix.stats.wifi.deadlineChecks} over ${matrix.deadlineMs} ms)`
                : 'Unavailable'}
            </strong>
            <strong>
              {matrix.lteDeadlineMissRate != null
                ? `${formatPercent(matrix.lteDeadlineMissRate)} (${matrix.stats.lte.deadlineMisses}/${matrix.stats.lte.deadlineChecks} over ${matrix.deadlineMs} ms)`
                : 'Unavailable'}
            </strong>
          </div>

          <div className="network-performance-table__row">
            <span>Link Switching Frequency</span>
            <span>How often the system changes communication paths.</span>
            <strong>
              {matrix.wifiSwitchPerMinute != null
                ? `${matrix.wifiSwitchPerMinute.toFixed(2)}/min (${matrix.switchoverBreakdown.wifi} to WiFi)`
                : 'Unavailable'}
            </strong>
            <strong>
              {matrix.lteSwitchPerMinute != null
                ? `${matrix.lteSwitchPerMinute.toFixed(2)}/min (${matrix.switchoverBreakdown.lte} to LTE)`
                : 'Unavailable'}
            </strong>
          </div>

          <div className="network-performance-table__row">
            <span>Bandwidth Overhead</span>
            <span>Extra network usage caused by redundant transmission.</span>
            <strong>
              {matrix.wifiOverhead != null
                ? `${formatPercent(matrix.wifiOverhead)} overhead (${formatBytes(matrix.wifiSentBytes)} sent)`
                : 'Unavailable'}
            </strong>
            <strong>
              {matrix.lteOverhead != null
                ? `${formatPercent(matrix.lteOverhead)} overhead (${formatBytes(matrix.lteSentBytes)} sent)`
                : 'Unavailable'}
            </strong>
          </div>
        </div>
      </div>

      <div className="stat-section">
        <h3>Distribution by mode and emulation</h3>
        {renderDistributionRows(distribution)}
      </div>
    </Panel>
  );
}
