import React, { useMemo } from 'react';
import { Panel } from '../../components/Panel';
import { formatClockTime } from '../../lib/format';
import { API_BASE_URL, DASHBOARD_WEBSOCKET_URL } from '../../lib/dashboardEndpoints';
import { DTNCounters, EXPERIMENT_MODE_LABELS, ExperimentMode, PiStatusReport } from '../../types';

const PI_REPORT_STALE_MS = 60_000;

interface DTNStatusPanelProps {
  connectionState: 'connecting' | 'open' | 'closed';
  status: PiStatusReport | null;
  counters: DTNCounters | null;
}

interface PathRow {
  label: string;
  state: string;
  detail: string;
  tone: 'good' | 'warn' | 'bad';
}

const formatReportAge = (ageMs: number): string => {
  if (ageMs < 60_000) {
    return `${Math.max(1, Math.round(ageMs / 1000))}s ago`;
  }
  if (ageMs < 3_600_000) {
    return `${Math.round(ageMs / 60_000)}m ago`;
  }
  return `${Math.round(ageMs / 3_600_000)}h ago`;
};

const getPiPathRows = (status: PiStatusReport | null): PathRow[] => {
  if (!status) {
    return [
      {
        label: 'Pi agent (telemetry path)',
        state: 'No data',
        detail: 'Waiting for pi_status from the agent over the Mac config channel.',
        tone: 'bad',
      },
    ];
  }

  const ageMs = Math.max(0, Date.now() - status.timestamp * 1000);
  const stale = ageMs > PI_REPORT_STALE_MS;

  return [
    {
      label: 'Pi agent (telemetry path)',
      state: stale ? 'Stale report' : 'Live',
      detail: `Last Pi status clock ${formatClockTime(status.timestamp * 1000, { includeMilliseconds: true })} · ${formatReportAge(ageMs)}`,
      tone: stale ? 'warn' : 'good',
    },
  ];
};

const getDtnActivityRow = (
  status: PiStatusReport | null,
  counters: DTNCounters | null,
): PathRow => {
  const bundlesFromPi =
    (status?.dtn_bundles_sent_wifi ?? 0) + (status?.dtn_bundles_sent_lte ?? 0);
  const bundlesFromStore = counters
    ? counters.bundles_sent_wifi + counters.bundles_sent_lte + counters.bundles_received
    : 0;

  if (bundlesFromPi > 0 || bundlesFromStore > 0) {
    return {
      label: 'DTN bundle path',
      state: 'Activity seen',
      detail:
        counters != null
          ? `Mac store: ${counters.bundles_received} in · ${counters.bundles_sent_wifi + counters.bundles_sent_lte} out (bundles). Pi-reported bundle totals: ${bundlesFromPi}.`
          : 'Counters loading — Pi reported non-zero bundle counts.',
      tone: 'good',
    };
  }

  if (status) {
    return {
      label: 'DTN bundle path',
      state: 'Idle',
      detail: 'No bundle counters yet; agent is up but no DTN bundle traffic recorded.',
      tone: 'warn',
    };
  }

  return {
    label: 'DTN bundle path',
    state: 'Unknown',
    detail: 'Need Pi status and counters to assess bundle flow.',
    tone: 'bad',
  };
};

export const DTNStatusPanel = ({ connectionState, status, counters }: DTNStatusPanelProps) => {
  const { piRows, bundleRow, dashboardRow, experimentLabel } = useMemo(() => {
    const piAgentRows = getPiPathRows(status);
    const dashboard: PathRow = {
      label: 'Dashboard stream',
      state:
        connectionState === 'open'
          ? 'Connected'
          : connectionState === 'connecting'
          ? 'Connecting'
          : 'Disconnected',
      detail: 'WebSocket from this browser to the Mac API (live pushes, not the Pi link).',
      tone: connectionState === 'open' ? 'good' : connectionState === 'connecting' ? 'warn' : 'bad',
    };
    const mode = status?.experiment_mode as ExperimentMode | undefined;
    const experimentLabelResolved =
      mode && EXPERIMENT_MODE_LABELS[mode] ? EXPERIMENT_MODE_LABELS[mode] : '—';

    return {
      bundleRow: getDtnActivityRow(status, counters),
      dashboardRow: dashboard,
      experimentLabel: experimentLabelResolved,
      piRows: piAgentRows,
    };
  }, [connectionState, counters, status]);

  const pathRows: PathRow[] = [dashboardRow, ...piRows, bundleRow];

  return (
    <Panel title="DTN Connections" className="stack-panel dtn-status-panel">
      <div className="status-table" role="list" aria-label="DTN and connection path status">
        {pathRows.map((row) => (
          <div key={row.label} className="status-row" role="listitem">
            <div className="status-row-title">
              <span className={`tone-dot tone-${row.tone}`} aria-hidden="true" />
              <strong>{row.label}</strong>
            </div>
            <span className={`status-badge tone-${row.tone}`}>{row.state}</span>
            <span className="status-detail">{row.detail}</span>
          </div>
        ))}
      </div>

      {status && (
        <div className="definition-list" aria-label="Experiment routing">
          <div>
            <span>Experiment mode</span>
            <strong>{experimentLabel}</strong>
          </div>
          <div>
            <span>Active link (DTN)</span>
            <strong
              className={
                status.active_link === 'wifi'
                  ? 'tone-good'
                  : status.active_link === 'lte'
                  ? 'tone-warn'
                  : 'tone-bad'
              }
            >
              {status.active_link.toUpperCase()}
            </strong>
          </div>
        </div>
      )}

      <div className="info-block endpoint-block" aria-label="Backend connection details">
        <div className="endpoint-lines">
          <div>
            <p className="info-label">REST API (snapshots)</p>
            <code className="endpoint-url">{API_BASE_URL}</code>
          </div>
          <div>
            <p className="info-label">WebSocket (live updates)</p>
            <code className="endpoint-url">{DASHBOARD_WEBSOCKET_URL}</code>
          </div>
        </div>
      </div>

      <p className="panel-footnote">
        &quot;Connected&quot; in the header refers to the dashboard WebSocket only. Pi reachability follows the Pi agent
        row above. Stale means no fresh pi_status for over {PI_REPORT_STALE_MS / 1000}s (by Pi timestamp).
      </p>
    </Panel>
  );
};
