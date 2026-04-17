import { PiStatusReport } from '../types';

/** Only surface queue depth in heartbeat text when backlog is meaningfully high. */
const QUEUE_SUMMARY_THRESHOLD = 25;

export function buildPiHeartbeatCopy(
  status: PiStatusReport,
  prefix?: string,
): { summary: string; detail: string | null } {
  const link = status.active_link !== 'none' ? status.active_link : 'none';
  const queuePart =
    status.queue_depth > QUEUE_SUMMARY_THRESHOLD
      ? `queue ${status.queue_depth}/1024 · `
      : '';
  const base = `${queuePart}active ${link}`;
  const summary = prefix ? `${prefix} · ${base}` : base;
  const detail = `WiFi ${status.wifi_reachable ? 'reachable' : '—'} · LTE ${
    status.lte_reachable ? 'reachable' : '—'
  } · scores w=${status.wifi_score?.toFixed(2) ?? '—'} lte=${status.lte_score?.toFixed(2) ?? '—'}`;
  return { summary, detail };
}
