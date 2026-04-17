import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { EmulationPanel } from '../control/EmulationPanel';
import { Panel } from '../../components/Panel';
import { ExperimentModePanel } from './ExperimentModePanel';
import { ExperimentResultsPanel } from './ExperimentResultsPanel';
import {
  CachedExperimentRecordingRun,
  EmulationSettings,
  ExperimentDistributionMetrics,
  ExperimentMetrics,
  EXPERIMENT_MODE_LABELS,
  PiStatusReport,
  RecentTelemetryResult,
  TelemetryMetrics,
} from '../../types';

type WorkspaceModal = 'strategy' | 'emulation' | null;

interface ExperimentWorkspacePanelProps {
  status: PiStatusReport | null;
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
  onStrategyApplied: () => void;
  onEmulationApplied: () => void;
}

const formatLinkProfile = (settings: EmulationSettings | null, label: string): string => {
  if (!settings) {
    return `${label}: —`;
  }

  const bandwidth =
    settings.bandwidth_kbps == null ? 'unlimited' : `${settings.bandwidth_kbps} kbps`;
  return `${label}: ${settings.delay_ms} ms delay, ${settings.jitter_ms} ms jitter, ${settings.loss_percent}% loss, ${bandwidth}${
    settings.outage ? ', outage' : ''
  }`;
};

const buildEmulationOverview = (status: PiStatusReport | null): string => {
  if (!status) {
    return 'Awaiting Pi status';
  }

  return `${formatLinkProfile(status.emulation_wifi, 'WiFi')} · ${formatLinkProfile(
    status.emulation_lte,
    'LTE',
  )}`;
};

const buildStrategyOverview = (status: PiStatusReport | null): string => {
  if (!status) {
    return 'Awaiting Pi status';
  }

  const mode = EXPERIMENT_MODE_LABELS[status.experiment_mode];
  const link = status.selected_link?.toUpperCase() ?? '—';
  return `${mode} · active link ${link}`;
};

export function ExperimentWorkspacePanel({
  status,
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
  onStrategyApplied,
  onEmulationApplied,
}: ExperimentWorkspacePanelProps) {
  const [openModal, setOpenModal] = useState<WorkspaceModal>(null);

  useEffect(() => {
    if (!openModal) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenModal(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [openModal]);

  const handleCloseModal = () => {
    setOpenModal(null);
  };

  const handleBackdropClick = () => {
    setOpenModal(null);
  };

  const renderModal = () => {
    if (!openModal) {
      return null;
    }

    const title =
      openModal === 'strategy' ? 'Communication strategy' : 'Network emulation';

    return createPortal(
      <div
        className="app-modal-backdrop"
        role="presentation"
        onClick={handleBackdropClick}
      >
        <section
          className="app-modal panel"
          role="dialog"
          aria-modal="true"
          aria-label={title}
          onClick={(event) => event.stopPropagation()}
        >
          <header className="app-modal__header">
            <div>
              <p className="eyebrow app-modal__eyebrow">
                {openModal === 'strategy' ? 'Experiment' : 'Network'}
              </p>
              <h3 className="app-modal__title">{title}</h3>
            </div>
            <button
              type="button"
              className="button button-secondary"
              onClick={handleCloseModal}
            >
              Close
            </button>
          </header>
          <div className="app-modal__body">
            {openModal === 'strategy' ? (
              <ExperimentModePanel
                variant="bare"
                status={status}
                onStrategyApplied={onStrategyApplied}
              />
            ) : (
              <EmulationPanel
                variant="bare"
                status={status}
                onEmulationApplied={onEmulationApplied}
              />
            )}
          </div>
        </section>
      </div>,
      document.body,
    );
  };

  return (
    <>
      <Panel title="Experiment" className="stack-panel experiment-workspace-panel">
        <div className="experiment-workspace-settings">
          <div className="experiment-workspace-row">
            <div className="experiment-workspace-row__meta">
              <p className="experiment-workspace-row__label">Communication strategy</p>
              <p className="experiment-workspace-row__summary">{buildStrategyOverview(status)}</p>
            </div>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setOpenModal('strategy')}
              aria-haspopup="dialog"
            >
              Modify
            </button>
          </div>
          <div className="experiment-workspace-row">
            <div className="experiment-workspace-row__meta">
              <p className="experiment-workspace-row__label">Network emulation</p>
              <p className="experiment-workspace-row__summary">{buildEmulationOverview(status)}</p>
            </div>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setOpenModal('emulation')}
              aria-haspopup="dialog"
            >
              Modify
            </button>
          </div>
        </div>

        <div className="stat-section experiment-workspace-results-heading">
          <h3>Emulation results</h3>
        </div>

        <ExperimentResultsPanel
          variant="bare"
          deadlineMetrics={deadlineMetrics}
          metrics={metrics}
          distribution={distribution}
          results={results}
          cachedRuns={cachedRuns}
          recordingReady={recordingReady}
          canStartRecording={canStartRecording}
          canStartTimedRun={canStartTimedRun}
          isRecording={isRecording}
          timedRunSecondsRemaining={timedRunSecondsRemaining}
          onStartRecording={onStartRecording}
          onStartTimedRun={onStartTimedRun}
          onStopRecording={onStopRecording}
        />
      </Panel>
      {renderModal()}
    </>
  );
}
