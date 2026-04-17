import React, { useState } from 'react';
import { api } from '../../api/client';
import { Panel } from '../../components/Panel';
import { formatClockTime } from '../../lib/format';
import { LinkMode, PiStatusReport } from '../../types';

interface LinkModePanelProps {
  status: PiStatusReport | null;
}

const MODES: { value: LinkMode; title: string; description: string }[] = [
  {
    value: 'wifi_only',
    title: 'WiFi only',
    description: 'Force DTN traffic over WiFi and keep LTE idle.',
  },
  {
    value: 'lte_only',
    title: 'LTE only',
    description: 'Force DTN traffic over LTE and suppress WiFi forwarding.',
  },
  {
    value: 'auto',
    title: 'Auto failover',
    description: 'Prefer WiFi and fail over to LTE when health drops.',
  },
];

export function LinkModePanel({ status }: LinkModePanelProps) {
  const [busy, setBusy] = useState<LinkMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSelectMode = async (mode: LinkMode) => {
    setBusy(mode);
    setError(null);

    try {
      await api.sendCommand({ cmd: 'set_mode', mode });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel title="Link Mode" className="stack-panel" busy={busy !== null}>
      <div className="definition-list">
        <div>
          <span>Active link</span>
          <strong
            className={
              status?.active_link === 'wifi'
                ? 'tone-good'
                : status?.active_link === 'lte'
                ? 'tone-warn'
                : 'tone-bad'
            }
          >
            {status?.active_link?.toUpperCase() ?? 'UNKNOWN'}
          </strong>
        </div>
        <div>
          <span>Last failover</span>
          <strong>
            {status?.last_failover_ts
              ? `${status.last_failover_direction ?? 'Direction unavailable'} at ${formatClockTime(
                  status.last_failover_ts * 1000,
                )}`
              : 'No failover recorded'}
          </strong>
        </div>
      </div>

      <div className="choice-stack" role="status" aria-live="polite">
        {MODES.map((mode) => {
          const isPending = busy === mode.value;

          return (
            <button
              key={mode.value}
              className={`choice-card ${
                status?.active_mode === mode.value ? 'is-active' : ''
              }`}
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
                <span className="choice-meta">
                  {status?.active_mode === mode.value ? 'Live' : 'Select'}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {error && <p className="message message-error">{error}</p>}
    </Panel>
  );
}
