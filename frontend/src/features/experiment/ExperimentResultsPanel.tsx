import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Panel } from '../../components/Panel';
import { formatClockTime, formatMs, formatPercent } from '../../lib/format';
import {
  CachedExperimentRecordingRun,
  EmulationSettings,
  ExperimentDistributionMetrics,
  ExperimentMetrics,
  EXPERIMENT_MODE_LABELS,
  RecentTelemetryResult,
  RecordedSessionSummary,
  TelemetryMetrics,
} from '../../types';
import { buildSessionSummary, getActiveSessionId } from './experimentRecordingUtils';

interface ExperimentResultsPanelProps {
  deadlineMetrics: TelemetryMetrics | null;
  metrics: ExperimentMetrics | null;
  distribution: ExperimentDistributionMetrics | null;
  results: RecentTelemetryResult[];
  cachedRuns: CachedExperimentRecordingRun[];
  recordingReady: boolean;
  canStartRecording: boolean;
  canStartTimedRun: boolean;
  isRecording: boolean;
  timedRunSecondsRemaining: number | null;
  onStartRecording: () => void;
  onStartTimedRun: () => void;
  onStopRecording: () => void;
  variant?: 'panel' | 'bare';
}

interface SessionMetricCardProps {
  label: string;
  value: string;
  detail: string;
  tone?: 'good' | 'warn' | 'bad';
}

function SessionMetricCard({ label, value, detail, tone }: SessionMetricCardProps) {
  return (
    <article className={`metric-card ${tone ? `metric-${tone}` : ''}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

function formatEmulationSettings(settings: EmulationSettings | null): string {
  if (!settings) {
    return 'default';
  }

  const bandwidth = settings.bandwidth_kbps == null ? 'unlimited' : `${settings.bandwidth_kbps} kbps`;
  return `delay ${settings.delay_ms} ms, jitter ${settings.jitter_ms} ms, loss ${settings.loss_percent}%, bandwidth ${bandwidth}${settings.outage ? ', outage' : ''}`;
}

function renderEmulationForSession(
  distribution: ExperimentDistributionMetrics | null,
  summaryRow: RecordedSessionSummary | null,
) {
  if (!distribution || !summaryRow) {
    return null;
  }

  const matchingBucket = distribution.buckets.find(
    (bucket) => bucket.experiment_mode === summaryRow.mode,
  );
  if (!matchingBucket) {
    return null;
  }

  return (
    <div className="experiment-distribution-emulation">
      <p>
        <strong>WiFi profile:</strong> {formatEmulationSettings(matchingBucket.emulation_wifi)}
      </p>
      <p>
        <strong>LTE profile:</strong> {formatEmulationSettings(matchingBucket.emulation_lte)}
      </p>
    </div>
  );
}

export function ExperimentResultsPanel({
  deadlineMetrics,
  metrics,
  distribution,
  results,
  cachedRuns,
  recordingReady,
  canStartRecording,
  canStartTimedRun,
  isRecording,
  timedRunSecondsRemaining,
  onStartRecording,
  onStartTimedRun,
  onStopRecording,
  variant = 'panel',
}: ExperimentResultsPanelProps) {
  const activeSessionId = useMemo(
    () => (isRecording ? getActiveSessionId(results) : null),
    [isRecording, results],
  );
  const activeRows = useMemo(
    () =>
      isRecording && activeSessionId
        ? results.filter((row) => row.experiment_session_id === activeSessionId)
        : [],
    [activeSessionId, isRecording, results],
  );
  const sessionSummaries = useMemo(() => buildSessionSummary(activeRows), [activeRows]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedSessionId) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedSessionId(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [selectedSessionId]);

  const selectedCachedRun = useMemo(
    () => cachedRuns.find((run) => `cached:${run.id}` === selectedSessionId) ?? null,
    [cachedRuns, selectedSessionId],
  );
  const selectedLiveSessionId =
    selectedSessionId && selectedSessionId.startsWith('live:')
      ? selectedSessionId.replace('live:', '')
      : null;
  const selectedLiveSummary = useMemo(
    () => sessionSummaries.find((row) => row.sessionId === selectedLiveSessionId) ?? null,
    [selectedLiveSessionId, sessionSummaries],
  );
  const selectedLiveRows = useMemo(
    () =>
      activeRows
        .filter((row) => row.experiment_session_id === selectedLiveSessionId)
        .sort((left, right) => right.ts - left.ts),
    [activeRows, selectedLiveSessionId],
  );
  const selectedSummary = selectedCachedRun ? selectedCachedRun.summary : selectedLiveSummary;
  const selectedRows = selectedCachedRun ? selectedCachedRun.rows : selectedLiveRows;
  const selectedDeadlineSnapshot = selectedCachedRun?.deadlineSnapshot ?? deadlineMetrics;
  const selectedMetricsSnapshot = selectedCachedRun?.metricsSnapshot ?? metrics;

  const hasCachedRuns = cachedRuns.length > 0;
  const showLiveResults = isRecording || hasCachedRuns;
  const cardsDeadlineMetrics = isRecording ? deadlineMetrics : cachedRuns[0]?.deadlineSnapshot ?? null;
  const cardsMetrics = isRecording ? metrics : cachedRuns[0]?.metricsSnapshot ?? null;

  const body = (
    <>
      <section className="metrics-grid">
        <SessionMetricCard
          label="Latency"
          value={showLiveResults && cardsMetrics ? formatMs(cardsMetrics.avg_latency_ms, 0) : '--'}
          detail={
            showLiveResults && cardsMetrics
              ? `p95 ${formatMs(cardsMetrics.p95_latency_ms, 0)} • max ${formatMs(cardsMetrics.max_latency_ms, 0)}`
              : cachedRuns.length > 0
                ? 'Showing most recently cached run'
                : 'Results appear while recording is active'
          }
          tone={
            showLiveResults && cardsMetrics?.avg_latency_ms != null && cardsMetrics.avg_latency_ms <= 1000
              ? 'good'
              : showLiveResults && cardsMetrics?.avg_latency_ms != null && cardsMetrics.avg_latency_ms <= 2000
                ? 'warn'
                : showLiveResults && cardsMetrics?.avg_latency_ms != null
                  ? 'bad'
                  : undefined
          }
        />
        <SessionMetricCard
          label="Delivery Rate"
          value={showLiveResults && cardsMetrics ? formatPercent(cardsMetrics.unique_delivery_rate) : '--'}
          detail={
            showLiveResults && cardsMetrics
              ? `${cardsMetrics.packets_unique_received}/${cardsMetrics.packets_enqueued || 0} unique packets`
              : cachedRuns.length > 0
                ? 'Showing most recently cached run'
                : 'Results appear while recording is active'
          }
          tone={
            showLiveResults && cardsMetrics && cardsMetrics.unique_delivery_rate >= 95
              ? 'good'
              : showLiveResults && cardsMetrics && cardsMetrics.unique_delivery_rate >= 75
                ? 'warn'
                : showLiveResults && cardsMetrics
                  ? 'bad'
                  : undefined
          }
        />
        <SessionMetricCard
          label="Deadline Success"
          value={showLiveResults && cardsDeadlineMetrics ? formatPercent(cardsDeadlineMetrics.deadline_success_rate) : '--'}
          detail={
            showLiveResults && cardsDeadlineMetrics
              ? `Target ${cardsDeadlineMetrics.deadline_ms} ms • ${cardsDeadlineMetrics.deadline_success_count} hits`
              : cachedRuns.length > 0
                ? 'Showing most recently cached run'
                : 'Results appear while recording is active'
          }
          tone={
            showLiveResults && cardsDeadlineMetrics && cardsDeadlineMetrics.deadline_success_rate >= 95
              ? 'good'
              : showLiveResults && cardsDeadlineMetrics && cardsDeadlineMetrics.deadline_success_rate >= 75
                ? 'warn'
                : showLiveResults && cardsDeadlineMetrics
                  ? 'bad'
                  : undefined
          }
        />
      </section>

      <div className="experiment-results-toolbar">
        <div className="experiment-results-toolbar__status">
          <span className="meta-label">Recording</span>
          <strong className={isRecording ? 'recording-state is-recording' : 'recording-state'}>
            <span className="recording-state__dot" aria-hidden="true" />
            {isRecording ? 'Recording' : 'Stopped'}
          </strong>
          {timedRunSecondsRemaining != null && (
            <span className="recording-state__timer">
              Timed run ends in {timedRunSecondsRemaining}s
            </span>
          )}
        </div>
        <div className="button-row">
          <button
            type="button"
            className="button"
            onClick={onStartRecording}
            disabled={!canStartRecording}
          >
            Start Recording
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={onStartTimedRun}
            disabled={!canStartTimedRun}
          >
            Run 30s
          </button>
          <button
            type="button"
            className="button button-secondary button-danger"
            onClick={onStopRecording}
            disabled={!isRecording}
          >
            Stop Experiment
          </button>
        </div>
      </div>

      {!recordingReady && (
        <p className="message">
          Recording is locked until both prerequisites are completed: set communication strategy, then
          apply emulation settings.
        </p>
      )}

      <div className="stat-section">
        <h3>Experiment sessions</h3>
        {!isRecording && hasCachedRuns ? (
          <div className="experiment-summary-table experiment-summary-table--sessions">
            <div className="experiment-summary-table__head experiment-summary-table__head--sessions">
              <span>Session</span>
              <span>Mode</span>
              <span>Packets</span>
              <span>Duplicates</span>
              <span>Latency avg / p95</span>
              <span>Queue wait avg</span>
              <span>Details</span>
            </div>
            {cachedRuns.map((run) => (
              <button
                key={run.id}
                type="button"
                className="experiment-summary-table__row experiment-summary-table__row--sessions experiment-summary-table__row--button"
                onClick={() => setSelectedSessionId(`cached:${run.id}`)}
                aria-label={`Open details for cached session ${run.summary.sessionId}`}
              >
                <strong>{run.summary.sessionId}</strong>
                <span>{EXPERIMENT_MODE_LABELS[run.summary.mode]}</span>
                <span>{run.summary.packetCount}</span>
                <span>{run.summary.duplicateCount}</span>
                <span>
                  {formatMs(run.summary.avgLatencyMs, 0)} / {formatMs(run.summary.p95LatencyMs, 0)}
                </span>
                <span>{formatMs(run.summary.avgQueueWaitMs, 0)}</span>
                <span className="session-row-action">View cached</span>
              </button>
            ))}
          </div>
        ) : !isRecording ? (
          <p className="empty-state">No cached run yet. Start and stop recording to store session results.</p>
        ) : sessionSummaries.length === 0 ? (
          <p className="empty-state">Waiting for active experiment samples.</p>
        ) : (
          <div className="experiment-summary-table experiment-summary-table--sessions">
            <div className="experiment-summary-table__head experiment-summary-table__head--sessions">
              <span>Session</span>
              <span>Mode</span>
              <span>Packets</span>
              <span>Duplicates</span>
              <span>Latency avg / p95</span>
              <span>Queue wait avg</span>
              <span>Details</span>
            </div>
            {sessionSummaries.map((row) => (
              <button
                key={row.sessionId}
                type="button"
                className="experiment-summary-table__row experiment-summary-table__row--sessions experiment-summary-table__row--button"
                onClick={() => setSelectedSessionId(`live:${row.sessionId}`)}
                aria-label={`Open details for session ${row.sessionId}`}
              >
                <strong>{row.sessionId}</strong>
                <span>{EXPERIMENT_MODE_LABELS[row.mode]}</span>
                <span>{row.packetCount}</span>
                <span>{row.duplicateCount}</span>
                <span>
                  {formatMs(row.avgLatencyMs, 0)} / {formatMs(row.p95LatencyMs, 0)}
                </span>
                <span>{formatMs(row.avgQueueWaitMs, 0)}</span>
                <span className="session-row-action">View details</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedSessionId &&
        createPortal(
          <div
            className="app-modal-backdrop"
            role="presentation"
            onClick={() => setSelectedSessionId(null)}
          >
            <section
              className="app-modal panel"
              role="dialog"
              aria-modal="true"
              aria-label={`Experiment session ${selectedSessionId} details`}
              onClick={(event) => event.stopPropagation()}
            >
              <header className="app-modal__header">
                <div>
                  <p className="eyebrow app-modal__eyebrow">Experiment session</p>
                  <h3 className="app-modal__title">{selectedSummary?.sessionId ?? selectedSessionId}</h3>
                </div>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setSelectedSessionId(null)}
                >
                  Close
                </button>
              </header>
              <div className="app-modal__body">
                {selectedSummary && (
                  <div className="definition-list compact-definition-list">
                    <div>
                      <span>Mode</span>
                      <strong>{EXPERIMENT_MODE_LABELS[selectedSummary.mode]}</strong>
                    </div>
                    <div>
                      <span>Packets</span>
                      <strong>{selectedSummary.packetCount}</strong>
                    </div>
                    <div>
                      <span>Avg latency</span>
                      <strong>{formatMs(selectedSummary.avgLatencyMs, 0)}</strong>
                    </div>
                    <div>
                      <span>Avg queue wait</span>
                      <strong>{formatMs(selectedSummary.avgQueueWaitMs, 0)}</strong>
                    </div>
                    <div>
                      <span>Deadline success</span>
                      <strong>
                        {selectedDeadlineSnapshot
                          ? formatPercent(selectedDeadlineSnapshot.deadline_success_rate)
                          : '—'}
                      </strong>
                    </div>
                    <div>
                      <span>Delivery rate</span>
                      <strong>
                        {selectedMetricsSnapshot
                          ? formatPercent(selectedMetricsSnapshot.unique_delivery_rate)
                          : '—'}
                      </strong>
                    </div>
                  </div>
                )}

                {renderEmulationForSession(distribution, selectedSummary)}

                <div className="telemetry-table-wrap">
                  <div className="telemetry-table-scroll">
                    <table className="telemetry-table">
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Seq</th>
                          <th>Packet</th>
                          <th>Mode</th>
                          <th>Selected</th>
                          <th>Winning</th>
                          <th>Latency</th>
                          <th>Queue wait</th>
                          <th>Altitude</th>
                          <th>Duplicate</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedRows.map((row) => (
                          <tr key={`${row.experiment_session_id}:${row.packet_id}:${row.sequence_number}`}>
                            <td>{formatClockTime(row.ts * 1000, { includeMilliseconds: true })}</td>
                            <td>{row.sequence_number}</td>
                            <td>{row.packet_id}</td>
                            <td>{EXPERIMENT_MODE_LABELS[row.experiment_mode]}</td>
                            <td>{row.selected_link.toUpperCase()}</td>
                            <td>{row.winning_link.toUpperCase()}</td>
                            <td>{formatMs(row.latency_ms, 0)}</td>
                            <td>{formatMs(row.queue_wait_ms, 0)}</td>
                            <td>{row.altitude.toFixed(2)} m</td>
                            <td>{row.had_duplicate ? 'Yes' : 'No'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </section>
          </div>,
          document.body,
        )}
    </>
  );

  if (variant === 'bare') {
    return (
      <div className="experiment-results-panel experiment-results-panel--bare">{body}</div>
    );
  }

  return (
    <Panel title="Emulation Results" className="traffic-panel">
      {body}
    </Panel>
  );
}
