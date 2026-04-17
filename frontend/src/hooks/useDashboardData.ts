import type { Dispatch, SetStateAction } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { buildPiHeartbeatCopy } from '../lib/piStatusHeartbeat';
import { useWebSocket } from '../api/websocket';
import {
  AltitudeTelemetry,
  DTNCounters,
  Event,
  ExperimentDistributionMetrics,
  ExperimentMetrics,
  PiStatusHeartbeatEntry,
  PiStatusReport,
  RecentTelemetryResult,
  TelemetryMetrics,
  WSMessage,
} from '../types';

const TELEMETRY_BUFFER_MAX = 500;
const STATUS_HEARTBEAT_MAX = 50;
const EVENTS_FETCH_LIMIT = 500;
const EVENTS_BUFFER_MAX = 500;
const RESULTS_BUFFER_MAX = 500;

let nextHeartbeatSeq = 0;

function pushStatusHeartbeat(
  setHeartbeats: Dispatch<SetStateAction<PiStatusHeartbeatEntry[]>>,
  status: PiStatusReport,
  prefix?: string,
) {
  const { summary, detail } = buildPiHeartbeatCopy(status, prefix);
  setHeartbeats((rows) => [
    ...rows.slice(-(STATUS_HEARTBEAT_MAX - 1)),
    {
      id: ++nextHeartbeatSeq,
      deviceTimestamp: status.timestamp,
      receivedAt: Date.now(),
      summary,
      detail,
    },
  ]);
}

export function useDashboardData() {
  const [status, setStatus] = useState<PiStatusReport | null>(null);
  const [counters, setCounters] = useState<DTNCounters | null>(null);
  const [metrics, setMetrics] = useState<TelemetryMetrics | null>(null);
  const [experimentMetrics, setExperimentMetrics] = useState<ExperimentMetrics | null>(null);
  const [experimentDistribution, setExperimentDistribution] =
    useState<ExperimentDistributionMetrics | null>(null);
  const [telemetry, setTelemetry] = useState<AltitudeTelemetry[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [results, setResults] = useState<RecentTelemetryResult[]>([]);
  const [statusHeartbeats, setStatusHeartbeats] = useState<PiStatusHeartbeatEntry[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);

    const [
      statusResult,
      countersResult,
      metricsResult,
      experimentMetricsResult,
      experimentDistributionResult,
      telemetryResult,
      resultsResult,
      eventsResult,
    ] = await Promise.allSettled([
      api.getStatus(),
      api.getDTNCounters(),
      api.getMetrics(),
      api.getExperimentMetrics(),
      api.getExperimentDistribution(),
      api.getTelemetry(200),
      api.getResults(200),
      api.getEvents(EVENTS_FETCH_LIMIT),
    ]);

    if (statusResult.status === 'fulfilled') {
      const snapshot = statusResult.value;
      setStatus(snapshot);
      pushStatusHeartbeat(setStatusHeartbeats, snapshot, 'Snapshot');
    }

    if (countersResult.status === 'fulfilled') {
      setCounters(countersResult.value);
    }

    if (metricsResult.status === 'fulfilled') {
      setMetrics(metricsResult.value);
    }

    if (experimentMetricsResult.status === 'fulfilled') {
      setExperimentMetrics(experimentMetricsResult.value);
    }

    if (experimentDistributionResult.status === 'fulfilled') {
      setExperimentDistribution(experimentDistributionResult.value);
    }

    if (telemetryResult.status === 'fulfilled') {
      setTelemetry(telemetryResult.value);
    }

    if (resultsResult.status === 'fulfilled') {
      setResults(resultsResult.value);
    }

    if (eventsResult.status === 'fulfilled') {
      setEvents(eventsResult.value);
    }

    const firstFailure = [
      statusResult,
      countersResult,
      metricsResult,
      experimentMetricsResult,
      experimentDistributionResult,
      telemetryResult,
      resultsResult,
      eventsResult,
    ].find((result) => result.status === 'rejected');

    if (firstFailure && firstFailure.status === 'rejected') {
      setError(
        firstFailure.reason instanceof Error
          ? firstFailure.reason.message
          : 'One or more requests failed',
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onMessage = useCallback((message: WSMessage) => {
    switch (message.type) {
      case 'pi_status': {
        const data = message.data;
        setStatus(data);
        pushStatusHeartbeat(setStatusHeartbeats, data);
        break;
      }
      case 'dtn_counters':
        setCounters(message.data);
        break;
      case 'metrics':
        setMetrics(message.data);
        break;
      case 'experiment_metrics':
        setExperimentMetrics(message.data);
        break;
      case 'experiment_distribution':
        setExperimentDistribution(message.data);
        break;
      case 'event':
        setEvents((current) => {
          if (current.some((existing) => existing.id === message.data.id)) {
            return current;
          }

          return [...current.slice(-(EVENTS_BUFFER_MAX - 1)), message.data];
        });
        break;
      case 'telemetry_result':
        setResults((current) => {
          const dedupKey = `${message.data.experiment_session_id}:${message.data.packet_id}`;
          const existingIndex = current.findIndex(
            (existing) => `${existing.experiment_session_id}:${existing.packet_id}` === dedupKey,
          );

          if (existingIndex >= 0) {
            const next = [...current];
            next[existingIndex] = message.data;
            return next;
          }

          const next = [...current, message.data];
          return next.length > RESULTS_BUFFER_MAX ? next.slice(-RESULTS_BUFFER_MAX) : next;
        });
        break;
      case 'bundle': {
        const payload = message.data;
        if (payload.msg_type === 'altitude_telemetry') {
          const sample: AltitudeTelemetry = payload;
          setTelemetry((current) => {
            const next = [...current, sample];
            return next.length > TELEMETRY_BUFFER_MAX
              ? next.slice(-TELEMETRY_BUFFER_MAX)
              : next;
          });
        }
        break;
      }
      default:
        break;
    }
  }, []);

  const connectionState = useWebSocket(onMessage);

  const refresh = useCallback(async () => {
    setRefreshing(true);

    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  const lastUpdated = useMemo(
    () => (status ? status.timestamp * 1000 : null),
    [status],
  );

  return {
    connectionState,
    counters,
    error,
    events,
    experimentMetrics,
    experimentDistribution,
    lastUpdated,
    metrics,
    results,
    refresh,
    refreshing,
    status,
    statusHeartbeats,
    telemetry,
  };
}
