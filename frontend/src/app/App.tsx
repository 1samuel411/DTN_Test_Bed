import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeftRight, Home, Settings, SlidersHorizontal } from 'lucide-react';
import { GPSPanel } from '../features/control/GPSPanel';
import { DTNStatusPanel } from '../features/dtn/DTNStatusPanel';
import { ConnectivityActivityPanel } from '../features/events/ConnectivityActivityPanel';
import { ExperimentActivityPanel } from '../features/events/ExperimentActivityPanel';
import { ExperimentWorkspacePanel } from '../features/experiment/ExperimentWorkspacePanel';
import { NetworkAnalyticsPanel } from '../features/experiment/NetworkAnalyticsPanel';
import { OperationsOverview } from '../features/overview/OperationsOverview';
import { CachedDeviceDataPanel } from '../features/settings/CachedDeviceDataPanel';
import { ConnectionStatusPanel } from '../features/status/ConnectionStatusPanel';
import { TelemetryPanel } from '../features/traffic/TelemetryPanel';
import { TrafficPanel } from '../features/traffic/TrafficPanel';
import { api } from '../api/client';
import {
  buildSessionSummary,
  getActiveSessionId,
  type LiveRecordingSnapshot,
} from '../features/experiment/experimentRecordingUtils';
import { useDashboardData } from '../hooks/useDashboardData';
import type { CachedExperimentRecordingRun } from '../types';
import { formatClockTime } from '../lib/format';

const RefreshIcon = () => (
  <svg
    className="app-live-header__refresh-icon"
    viewBox="0 0 24 24"
    width={14}
    height={14}
    fill="currentColor"
    aria-hidden="true"
  >
    <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" />
  </svg>
);

type DashboardSection = 'home' | 'emulation' | 'traffic' | 'settings';

const DASHBOARD_SECTIONS: Array<{ id: DashboardSection; label: string }> = [
  { id: 'home', label: 'Home' },
  { id: 'emulation', label: 'Emulation' },
  { id: 'traffic', label: 'Traffic' },
  { id: 'settings', label: 'Settings' },
];
const TIMED_EXPERIMENT_SECONDS = 30;

function MenuIcon({ section }: { section: DashboardSection }) {
  if (section === 'home') {
    return <Home size={16} strokeWidth={2} aria-hidden="true" />;
  }

  if (section === 'emulation') {
    return <SlidersHorizontal size={16} strokeWidth={2} aria-hidden="true" />;
  }

  if (section === 'traffic') {
    return <ArrowLeftRight size={16} strokeWidth={2} aria-hidden="true" />;
  }

  return <Settings size={16} strokeWidth={2} aria-hidden="true" />;
}

export function App() {
  const [activeSection, setActiveSection] = useState<DashboardSection>('home');
  const [hasConfiguredStrategy, setHasConfiguredStrategy] = useState(false);
  const [hasConfiguredEmulation, setHasConfiguredEmulation] = useState(false);
  const [isExperimentRecording, setIsExperimentRecording] = useState(false);
  const [timedRunSecondsRemaining, setTimedRunSecondsRemaining] = useState<number | null>(null);
  const timedRunIntervalRef = useRef<number | null>(null);
  const [cachedExperimentRuns, setCachedExperimentRuns] = useState<CachedExperimentRecordingRun[]>([]);
  const wasExperimentRecordingRef = useRef(false);
  const latestExperimentRunRef = useRef<LiveRecordingSnapshot | null>(null);
  const experimentStopPersistInFlightRef = useRef(false);
  const {
    connectionState,
    counters,
    error,
    events,
    experimentDistribution,
    experimentMetrics,
    lastUpdated,
    metrics,
    results,
    refresh,
    refreshing,
    status,
    statusHeartbeats,
    telemetry,
  } = useDashboardData();

  const handleSelectSection = (section: DashboardSection) => {
    setActiveSection(section);
  };

  const handleStrategyApplied = useCallback(() => {
    setHasConfiguredStrategy(true);
    void refresh();
  }, [refresh]);

  const handleEmulationApplied = () => {
    setHasConfiguredEmulation(true);
  };

  const revertEmulationAfterExperiment = async () => {
    try {
      await api.sendCommand({ cmd: 'revert_emulation', interface_role: 'both' });
      setHasConfiguredEmulation(false);
    } catch {
      // Offline or command failed — shaping may still be active; leave flags unchanged.
    }
  };

  const recordingReady = hasConfiguredStrategy && hasConfiguredEmulation;
  const canStartRecording = recordingReady && !isExperimentRecording;
  const canStartTimedRun = recordingReady && !isExperimentRecording;

  const clearTimedRunInterval = () => {
    if (timedRunIntervalRef.current != null) {
      window.clearInterval(timedRunIntervalRef.current);
      timedRunIntervalRef.current = null;
    }
  };

  const handleStartExperimentRecording = () => {
    if (!canStartRecording) {
      return;
    }
    clearTimedRunInterval();
    setTimedRunSecondsRemaining(null);
    setIsExperimentRecording(true);
  };

  const handleStopExperimentRecording = () => {
    clearTimedRunInterval();
    setTimedRunSecondsRemaining(null);
    setIsExperimentRecording(false);
    void revertEmulationAfterExperiment();
  };

  const handleStartTimedRun = () => {
    if (!canStartTimedRun) {
      return;
    }

    clearTimedRunInterval();
    setIsExperimentRecording(true);
    setTimedRunSecondsRemaining(TIMED_EXPERIMENT_SECONDS);
    timedRunIntervalRef.current = window.setInterval(() => {
      setTimedRunSecondsRemaining((current) => {
        if (current == null) {
          return null;
        }
        if (current <= 1) {
          clearTimedRunInterval();
          setIsExperimentRecording(false);
          void revertEmulationAfterExperiment();
          return null;
        }
        return current - 1;
      });
    }, 1000);
  };

  useEffect(() => {
    return () => {
      clearTimedRunInterval();
    };
  }, []);

  const refreshCachedExperimentRuns = useCallback(async () => {
    try {
      const rows = await api.getExperimentRecordingRuns(20);
      setCachedExperimentRuns(rows);
    } catch {
      // Older backend or offline: leave list unchanged.
    }
  }, []);

  useEffect(() => {
    void refreshCachedExperimentRuns();
  }, [refreshCachedExperimentRuns]);

  useEffect(() => {
    if (activeSection === 'emulation') {
      void refreshCachedExperimentRuns();
    }
  }, [activeSection, refreshCachedExperimentRuns]);

  useEffect(() => {
    if (!isExperimentRecording) {
      return;
    }
    const activeSessionId = getActiveSessionId(results);
    if (!activeSessionId) {
      return;
    }
    const activeRows = results.filter((row) => row.experiment_session_id === activeSessionId);
    if (activeRows.length === 0) {
      return;
    }
    latestExperimentRunRef.current = {
      sessionId: activeSessionId,
      rows: activeRows,
      metricsSnapshot: experimentMetrics,
      deadlineSnapshot: metrics,
    };
  }, [isExperimentRecording, results, experimentMetrics, metrics]);

  useEffect(() => {
    const wasRecording = wasExperimentRecordingRef.current;
    if (
      wasRecording &&
      !isExperimentRecording &&
      latestExperimentRunRef.current &&
      !experimentStopPersistInFlightRef.current
    ) {
      experimentStopPersistInFlightRef.current = true;
      const snap = latestExperimentRunRef.current;
      void (async () => {
        try {
          const summary =
            buildSessionSummary(snap.rows).find((row) => row.sessionId === snap.sessionId) ??
            buildSessionSummary(snap.rows)[0];
          if (!summary) {
            return;
          }
          await api.postExperimentRecordingRun({
            experiment_session_id: summary.sessionId,
            stopped_at_ms: Date.now(),
            summary,
            rows: snap.rows,
            metrics_snapshot: snap.metricsSnapshot,
            deadline_snapshot: snap.deadlineSnapshot,
          });
          await refreshCachedExperimentRuns();
        } catch {
          // Persistence failed.
        } finally {
          experimentStopPersistInFlightRef.current = false;
        }
      })();
    }
    wasExperimentRecordingRef.current = isExperimentRecording;
  }, [isExperimentRecording, refreshCachedExperimentRuns]);

  const renderSectionContent = () => {
    if (activeSection === 'home') {
      return (
        <section className="dashboard-section-grid">
          <OperationsOverview
            connectionState={connectionState}
            counters={counters}
            experimentMetrics={experimentMetrics}
            metrics={metrics}
            status={status}
          />
          <TelemetryPanel telemetry={telemetry} />
        </section>
      );
    }

    if (activeSection === 'emulation') {
      return (
        <section className="dashboard-section-grid">
          <div className="test-profile-flow">
            <ExperimentWorkspacePanel
              status={status}
              deadlineMetrics={metrics}
              metrics={experimentMetrics}
              distribution={experimentDistribution}
              results={results}
              cachedRuns={cachedExperimentRuns}
              recordingReady={recordingReady}
              canStartRecording={canStartRecording}
              canStartTimedRun={canStartTimedRun}
              isRecording={isExperimentRecording}
              timedRunSecondsRemaining={timedRunSecondsRemaining}
              onStartRecording={handleStartExperimentRecording}
              onStartTimedRun={handleStartTimedRun}
              onStopRecording={handleStopExperimentRecording}
              onStrategyApplied={handleStrategyApplied}
              onEmulationApplied={handleEmulationApplied}
            />
          </div>
          <NetworkAnalyticsPanel
            counters={counters}
            deadlineMetrics={metrics}
            distribution={experimentDistribution}
            metrics={experimentMetrics}
            status={status}
            telemetry={telemetry}
          />
          <ExperimentActivityPanel events={events} metrics={experimentMetrics} status={status} />
        </section>
      );
    }

    if (activeSection === 'traffic') {
      return (
        <section className="dashboard-section-grid">
          <TrafficPanel
            counters={counters}
            experimentMetrics={experimentMetrics}
            metrics={metrics}
            status={status}
          />
          <ConnectivityActivityPanel events={events} statusHeartbeats={statusHeartbeats} />
        </section>
      );
    }

    return (
      <section className="dashboard-section-grid">
        <DTNStatusPanel connectionState={connectionState} counters={counters} status={status} />
        <ConnectionStatusPanel status={status} />
        <GPSPanel status={status} />
        <CachedDeviceDataPanel onCleared={refresh} />
      </section>
    );
  };

  return (
    <div className="app-shell">
      <div className="app-shell__bg" aria-hidden="true">
        <div className="app-shell__bg-art" />
        <div className="app-shell__bg-fade" />
      </div>
      <header className="app-floating-header" aria-label="DTN Testbed and connection controls">
        <div className="app-floating-header__inner">
          <div className="app-floating-header__surface panel">
            <div className="app-floating-header__left">
              <div className="app-floating-header__title-row">
                <img
                  src="/dual-channel-icon.svg"
                  alt=""
                  className="app-floating-header__title-icon"
                  width={64}
                  height={64}
                  decoding="async"
                />
                <div className="app-floating-header__title-block">
                  <h1 className="app-floating-header__title">
                    <span>DTN Testbed</span>
                  </h1>
                  <p className="eyebrow app-floating-header__eyebrow">
                    Delay-Tolerant Networking Operations
                  </p>
                </div>
              </div>
            </div>

            <div className="app-floating-header__right">
              <div className="app-floating-header__device">
                <span className="meta-label">Device</span>
                <strong>{status?.device_id ?? 'Awaiting Pi status'}</strong>
              </div>
              <span className="app-floating-header__divider" aria-hidden="true">
                |
              </span>
              <div className="app-floating-header__live">
                <div
                  className="app-live-header__pill-status"
                  role="status"
                  aria-live="polite"
                  aria-label="Connection status and last snapshot time"
                >
                  <span className="app-live-header__status-row">
                    <span
                      className={`status-indicator status-indicator--compact status-${connectionState}`}
                      aria-hidden="true"
                    />
                    <span>
                      {connectionState === 'open'
                        ? 'Connected'
                        : connectionState === 'connecting'
                        ? 'Connecting'
                        : 'Disconnected'}
                    </span>
                  </span>
                  <span className="app-live-header__status-row app-live-header__status-row--time">
                    <span className="app-live-header__tiny-label">Last update</span>
                    {lastUpdated ? (
                      <time dateTime={new Date(lastUpdated).toISOString()}>
                        {formatClockTime(lastUpdated, { includeMilliseconds: true })}
                      </time>
                    ) : (
                      <span>—</span>
                    )}
                  </span>
                </div>
                <span className="app-live-header__pill-divider" aria-hidden="true" />
                <button
                  className="app-live-header__icon-btn"
                  type="button"
                  onClick={() => void refresh()}
                  disabled={refreshing}
                  aria-busy={refreshing}
                  aria-label={refreshing ? 'Refreshing snapshot' : 'Refresh snapshot'}
                >
                  {refreshing ? (
                    <span className="app-live-header__spinner" aria-hidden="true" />
                  ) : (
                    <RefreshIcon />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="app-main">
        <aside id="dashboard-side-menu" className="app-slideout-menu" aria-label="Dashboard sections">
          <p className="app-slideout-menu__title">Dashboard Menu</p>
          <nav className="app-slideout-menu__list">
            {DASHBOARD_SECTIONS.map((section) => {
              const isActive = section.id === activeSection;
              return (
                <button
                  key={section.id}
                  type="button"
                  className={`app-slideout-menu__item ${isActive ? 'is-active' : ''} ${
                    section.id === 'settings' ? 'app-slideout-menu__item--bottom' : ''
                  }`}
                  onClick={() => handleSelectSection(section.id)}
                  aria-current={isActive ? 'page' : undefined}
                  aria-label={`${section.label} section`}
                >
                  <span className="app-slideout-menu__item-main">
                    <span className="app-slideout-menu__emoji" aria-hidden="true">
                      <MenuIcon section={section.id} />
                    </span>
                    <span>{section.label}</span>
                  </span>
                </button>
              );
            })}
          </nav>
        </aside>

        <div className="app-main-with-sidebar">
          {error && (
            <section className="banner banner-warning" role="status">
              <strong>Initial data load issue.</strong> {error}
            </section>
          )}

          <section className="app-workspace" aria-label="Dashboard workspace">
            <div className="app-workspace__content">{renderSectionContent()}</div>
          </section>
        </div>
      </main>
    </div>
  );
}
