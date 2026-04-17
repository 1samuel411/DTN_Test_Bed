import type { ExperimentMetrics, RecentTelemetryResult, RecordedSessionSummary, TelemetryMetrics } from '../../types';

export interface LiveRecordingSnapshot {
  sessionId: string;
  rows: RecentTelemetryResult[];
  metricsSnapshot: ExperimentMetrics | null;
  deadlineSnapshot: TelemetryMetrics | null;
}

function percentile(values: number[], ratio: number): number | null {
  if (values.length === 0) {
    return null;
  }

  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.max(0, Math.min(sorted.length - 1, Math.floor(ratio * (sorted.length - 1))));
  return sorted[index];
}

export function buildSessionSummary(rows: RecentTelemetryResult[]): RecordedSessionSummary[] {
  const grouped = new Map<string, RecentTelemetryResult[]>();
  rows.forEach((row) => {
    const key = row.experiment_session_id || 'unknown-session';
    const current = grouped.get(key) ?? [];
    current.push(row);
    grouped.set(key, current);
  });

  return [...grouped.entries()]
    .map(([sessionId, sessionRows]) => {
      const latencies = sessionRows.map((row) => row.latency_ms);
      const queueWaits = sessionRows.map((row) => row.queue_wait_ms);
      const packetCount = sessionRows.length;
      const duplicateCount = sessionRows.filter((row) => row.had_duplicate).length;
      const latest = sessionRows.reduce((latestRow, currentRow) =>
        currentRow.ts > latestRow.ts ? currentRow : latestRow,
      );
      const latencySum = latencies.reduce((sum, value) => sum + value, 0);
      const queueWaitSum = queueWaits.reduce((sum, value) => sum + value, 0);

      return {
        sessionId,
        mode: latest.experiment_mode,
        packetCount,
        duplicateCount,
        avgLatencyMs: packetCount > 0 ? latencySum / packetCount : null,
        p95LatencyMs: percentile(latencies, 0.95),
        avgQueueWaitMs: packetCount > 0 ? queueWaitSum / packetCount : null,
        latestTs: latest.ts,
      };
    })
    .sort((left, right) => right.latestTs - left.latestTs);
}

export function getActiveSessionId(rows: RecentTelemetryResult[]): string | null {
  if (rows.length === 0) {
    return null;
  }

  const latest = rows.reduce((latestRow, currentRow) =>
    currentRow.ts > latestRow.ts ? currentRow : latestRow,
  );

  return latest.experiment_session_id || null;
}
