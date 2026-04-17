import React from 'react';
import { Panel } from '../../components/Panel';
import { formatClockTime } from '../../lib/format';
import { PiStatusReport } from '../../types';

interface ConnectionStatusPanelProps {
  status: PiStatusReport | null;
}

interface StatusRow {
  label: string;
  state: string;
  detail: string;
  tone: 'good' | 'warn' | 'bad';
}

/** Layer-2 up but no IPv4 yet vs has IP but DTN probe to Mac failed */
const linkRowState = (
  reachable: boolean,
  up: boolean,
  ip: string | null
): string => {
  if (reachable) return 'Reachable';
  if (!up) return 'Down';
  if (!ip) return 'Up (no IPv4 yet)';
  return 'Up without route';
};

function buildRows(status: PiStatusReport): StatusRow[] {
  return [
    {
      label: 'WiFi',
      state: linkRowState(status.wifi_reachable, status.wifi_up, status.wifi_ip),
      detail: `${status.wifi_interface ?? 'No interface'} • ${status.wifi_ip ?? 'No address'}`,
      tone: status.wifi_reachable ? 'good' : status.wifi_up ? 'warn' : 'bad',
    },
    {
      label: 'LTE',
      state: linkRowState(status.lte_reachable, status.lte_up, status.lte_ip),
      detail: `${status.lte_interface ?? 'No interface'} • ${status.lte_ip ?? 'No address'}`,
      tone: status.lte_reachable ? 'good' : status.lte_up ? 'warn' : 'bad',
    },
    {
      label: 'Ethernet',
      state: status.eth_up ? 'Management up' : 'Down',
      detail: `${status.eth_interface ?? 'No interface'} • ${status.eth_ip ?? 'No address'}`,
      tone: status.eth_up ? 'good' : 'bad',
    },
    {
      label: 'GPS',
      state: status.gps_connected
        ? `Connected (${status.gps_fix_state})`
        : 'Disconnected',
      detail: `${status.gps_device ?? 'No device'} • ${status.gps_baudrate} baud`,
      tone:
        status.gps_connected && status.gps_fix_state !== 'no_fix'
          ? 'good'
          : status.gps_connected
          ? 'warn'
          : 'bad',
    },
  ];
}

export function ConnectionStatusPanel({ status }: ConnectionStatusPanelProps) {
  return (
    <Panel title="Network Health" className="status-panel">
      {status ? (
        <>
          <div className="status-table">
            {buildRows(status).map((row) => (
              <div key={row.label} className="status-row">
                <div className="status-row-title">
                  <span className={`tone-dot tone-${row.tone}`} aria-hidden="true" />
                  <strong>{row.label}</strong>
                </div>
                <span className={`status-badge tone-${row.tone}`}>{row.state}</span>
                <span className="status-detail">{row.detail}</span>
              </div>
            ))}
          </div>

          <p className="panel-footnote">
            Last Pi report received at {formatClockTime(status.timestamp * 1000)}.
          </p>
        </>
      ) : (
        <p className="empty-state">Waiting for the first Pi status report.</p>
      )}
    </Panel>
  );
}
