import React, { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { Panel } from '../../components/Panel';
import { formatClockTime } from '../../lib/format';
import { EXPERIMENT_MODE_LABELS, ExperimentMode, PiStatusReport } from '../../types';

interface ExperimentModePanelProps {
  status: PiStatusReport | null;
  onStrategyApplied?: () => void;
  /** When `bare`, renders inner content only (for embedding in a modal or composite panel). */
  variant?: 'panel' | 'bare';
}

const NON_SINGLE_LINK_MODES: { value: ExperimentMode; title: string; description: string }[] = [
  {
    value: 'adaptive',
    title: 'Adaptive',
    description: 'Score both links and switch deterministically when the challenger stays better.',
  },
  {
    value: 'redundant',
    title: 'Redundant',
    description: 'Transmit each telemetry packet over both links and accept the first arrival only.',
  },
];

export function ExperimentModePanel({
  status,
  onStrategyApplied,
  variant = 'panel',
}: ExperimentModePanelProps) {
  const [busy, setBusy] = useState<ExperimentMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [singleLinkChoice, setSingleLinkChoice] = useState<'wifi' | 'lte'>('lte');

  const isSingleLinkMode =
    status?.experiment_mode === 'single_link_wifi' || status?.experiment_mode === 'single_link_lte';

  // Keep the WiFi/LTE control in sync when the Pi reports a single-link mode, but allow local
  // toggles while still in that mode (otherwise clicks are ignored because status overrides state).
  useEffect(() => {
    if (status?.experiment_mode === 'single_link_wifi') {
      setSingleLinkChoice('wifi');
      return;
    }
    if (status?.experiment_mode === 'single_link_lte') {
      setSingleLinkChoice('lte');
    }
  }, [status?.experiment_mode]);

  const selectedSingleLinkMode: ExperimentMode =
    singleLinkChoice === 'wifi' ? 'single_link_wifi' : 'single_link_lte';

  const handleSelectMode = async (mode: ExperimentMode) => {
    setBusy(mode);
    setError(null);

    try {
      await api.sendCommand({ cmd: 'set_experiment_mode', mode });
      onStrategyApplied?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setBusy(null);
    }
  };

  const handleSingleLinkCardClick = (event: React.MouseEvent<HTMLElement>) => {
    if (busy !== null) {
      return;
    }
    const target = event.target as HTMLElement;
    if (target.closest('.single-link-selector')) {
      return;
    }
    void handleSelectMode(selectedSingleLinkMode);
  };

  const body = (
    <>
      <div className="definition-list">
        <div>
          <span>Current mode</span>
          <strong>
            {status ? EXPERIMENT_MODE_LABELS[status.experiment_mode] : 'Awaiting Pi status'}
          </strong>
        </div>
        <div>
          <span>Selected link</span>
          <strong>{status?.selected_link?.toUpperCase() ?? '—'}</strong>
        </div>
        <div>
          <span>Decision reason</span>
          <strong>{status?.decision_reason ?? '—'}</strong>
        </div>
        <div>
          <span>Last switchover</span>
          <strong>
            {status?.last_failover_ts
              ? `${status.last_failover_direction ?? 'unknown'} at ${formatClockTime(
                  status.last_failover_ts * 1000,
                )}`
              : 'No switchover recorded'}
          </strong>
        </div>
      </div>

      <div className="choice-stack" role="status" aria-live="polite">
        <section
          className={`choice-card single-link-card ${isSingleLinkMode ? 'is-active' : ''}`}
          aria-label="Single Link mode"
          onClick={handleSingleLinkCardClick}
        >
          <div>
            <strong>Single Link</strong>
            <p>Use one DTN transmission path only. Choose WiFi or LTE as the fixed path.</p>
            <div
              className="segmented single-link-selector"
              role="group"
              aria-label="Single link choice"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                className={`segmented-button ${
                  singleLinkChoice === 'wifi' ? 'is-active' : ''
                }`}
                onClick={() => setSingleLinkChoice('wifi')}
                disabled={busy !== null}
                aria-pressed={singleLinkChoice === 'wifi'}
              >
                WiFi
              </button>
              <button
                type="button"
                className={`segmented-button ${
                  singleLinkChoice === 'lte' ? 'is-active' : ''
                }`}
                onClick={() => setSingleLinkChoice('lte')}
                disabled={busy !== null}
                aria-pressed={singleLinkChoice === 'lte'}
              >
                LTE
              </button>
            </div>
          </div>
          {busy === selectedSingleLinkMode ? (
            <span className="choice-meta choice-meta--pending">
              <span className="inline-spinner" aria-hidden="true" />
              Applying...
            </span>
          ) : (
            <span className="choice-meta single-link-apply">
              {isSingleLinkMode ? 'Live' : 'Select'}
            </span>
          )}
        </section>

        {NON_SINGLE_LINK_MODES.map((mode) => {
          const isPending = busy === mode.value;
          const isActive = status?.experiment_mode === mode.value;

          return (
            <button
              key={mode.value}
              className={`choice-card ${isActive ? 'is-active' : ''}`}
              type="button"
              onClick={() => void handleSelectMode(mode.value)}
              disabled={busy !== null}
              aria-busy={isPending}
            >
              <div>
                <strong>{mode.title}</strong>
                <p>{mode.description}</p>
              </div>
              {isPending ? (
                <span className="choice-meta choice-meta--pending">
                  <span className="inline-spinner" aria-hidden="true" />
                  Applying…
                </span>
              ) : (
                <span className="choice-meta">{isActive ? 'Live' : 'Select'}</span>
              )}
            </button>
          );
        })}
      </div>

      {error && <p className="message message-error">{error}</p>}
    </>
  );

  if (variant === 'bare') {
    return (
      <div className="experiment-mode-panel experiment-mode-panel--bare" aria-busy={busy !== null}>
        {body}
      </div>
    );
  }

  return (
    <Panel title="Communication Strategy" className="stack-panel" busy={busy !== null}>
      {body}
    </Panel>
  );
}
