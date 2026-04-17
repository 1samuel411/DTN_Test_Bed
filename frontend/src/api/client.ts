/**
 * REST API client.
 * Base URL is read from VITE_API_URL env var.
 */
import { API_BASE_URL } from '../lib/dashboardEndpoints';
import {
  AltitudeTelemetry,
  CachedExperimentRecordingRun,
  DTNCounters,
  Event,
  ExperimentDistributionMetrics,
  ExperimentMetrics,
  ExperimentRecordingRunPayload,
  MgmtCommand,
  PiStatusReport,
  RecentTelemetryResult,
  TelemetryMetrics,
} from '../types';

const BASE = API_BASE_URL;

function isNotFoundError(error: unknown): boolean {
  return error instanceof Error && error.message.includes('-> 404');
}

async function _get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`GET ${path} -> ${res.status}`);
  }
  return res.json();
}

async function _post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`POST ${path} -> ${res.status}`);
  }
  return res.json();
}

export const api = {
  getStatus:    () => _get<PiStatusReport>('/api/status'),
  getTelemetry: (limit = 50) =>
    _get<AltitudeTelemetry[]>(`/api/telemetry?limit=${limit}`),
  getResults: (limit = 50) =>
    _get<RecentTelemetryResult[]>(`/api/results?limit=${limit}`),
  getExperimentMetrics: () => _get<ExperimentMetrics>('/api/metrics/experiment'),
  getExperimentDistribution: async () => {
    try {
      return await _get<ExperimentDistributionMetrics>('/api/metrics/experiment/distribution');
    } catch (error) {
      // Older backend builds do not expose this endpoint yet.
      if (isNotFoundError(error)) {
        return {
          updated_ts: 0,
          total_buckets: 0,
          buckets: [],
        };
      }
      throw error;
    }
  },
  getEvents:    (limit = 100) => _get<Event[]>(`/api/events?limit=${limit}`),
  getDTNCounters: () => _get<DTNCounters>('/api/dtn/counters'),
  getMetrics:   () => _get<TelemetryMetrics>('/api/metrics'),
  getExperimentRecordingRuns: (limit = 20) =>
    _get<CachedExperimentRecordingRun[]>(`/api/experiment-recording-runs?limit=${limit}`),
  postExperimentRecordingRun: (body: ExperimentRecordingRunPayload) =>
    _post<{ id: string }>('/api/experiment-recording-runs', body),
  sendCommand:  (cmd: MgmtCommand) => _post<{ ok: boolean }>('/api/command', cmd),
};
