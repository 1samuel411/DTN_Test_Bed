import React, { useMemo } from 'react';
import { Panel } from '../../components/Panel';
import { formatClockTime } from '../../lib/format';
import { Event, PiStatusHeartbeatEntry } from '../../types';

interface ConnectivityActivityPanelProps {
  events: Event[];
  statusHeartbeats: PiStatusHeartbeatEntry[];
}

type ConnectivitySortRow =
  | {
      id: string;
      kind: 'gps';
      summary: string;
      detail: string | null;
      deviceTimestampMs: number;
      receivedTimestampMs: number | null;
      sortMs: number;
    }
  | {
      id: string;
      kind: 'heartbeat';
      summary: string;
      detail: string | null;
      deviceTimestampMs: number;
      receivedTimestampMs: number;
      sortMs: number;
    };

const MAX_ROWS = 60;

export function ConnectivityActivityPanel({
  events,
  statusHeartbeats,
}: ConnectivityActivityPanelProps) {
  const rows = useMemo(() => {
    const gpsRows: ConnectivitySortRow[] = events
      .filter((event) => event.event_type === 'gps_status')
      .map((event) => ({
        id: `gps-${event.id}`,
        kind: 'gps' as const,
        summary: event.summary,
        detail: event.detail,
        deviceTimestampMs: event.timestamp * 1000,
        receivedTimestampMs: null,
        sortMs: event.timestamp * 1000,
      }));

    const hbRows: ConnectivitySortRow[] = statusHeartbeats.map((entry) => ({
      id: `hb-${entry.id}`,
      kind: 'heartbeat' as const,
      summary: entry.summary,
      detail: entry.detail,
      deviceTimestampMs: entry.deviceTimestamp * 1000,
      receivedTimestampMs: entry.receivedAt,
      sortMs: entry.deviceTimestamp * 1000,
    }));

    return [...gpsRows, ...hbRows].sort((a, b) => b.sortMs - a.sortMs).slice(0, MAX_ROWS);
  }, [events, statusHeartbeats]);

  return (
    <Panel title="Connectivity Activity" className="events-panel">
      {rows.length === 0 ? (
        <p className="empty-state">No GPS or Pi status updates yet.</p>
      ) : (
        <div className="connectivity-table-wrap">
          <p className="panel-footnote">
            Showing latest {rows.length} connectivity rows (GPS status bundles + Pi status heartbeats).
          </p>
          <div className="connectivity-table-scroll">
            <table className="connectivity-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Summary</th>
                  <th>Details</th>
                  <th>Device time</th>
                  <th>Received time</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span
                        className={`event-pill ${
                          row.kind === 'gps' ? 'event-gps_status' : 'event-heartbeat'
                        }`}
                      >
                        {row.kind === 'gps' ? 'GPS bundle' : 'Pi heartbeat'}
                      </span>
                    </td>
                    <td>{row.summary}</td>
                    <td>{row.detail || '—'}</td>
                    <td>{formatClockTime(row.deviceTimestampMs, { includeMilliseconds: true })}</td>
                    <td>
                      {row.receivedTimestampMs
                        ? formatClockTime(row.receivedTimestampMs, { includeMilliseconds: true })
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Panel>
  );
}
