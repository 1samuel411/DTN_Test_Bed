import React, { useMemo } from 'react';
import { Panel } from '../../components/Panel';
import { formatClockTime } from '../../lib/format';
import { Event, ExperimentMetrics, EXPERIMENT_MODE_LABELS, PiStatusReport } from '../../types';

interface ExperimentActivityPanelProps {
  events: Event[];
  metrics: ExperimentMetrics | null;
  status: PiStatusReport | null;
}

/** DTN / experiment events — not per-packet telemetry or GPS/heartbeat noise. */
const EXPERIMENT_EVENT_TYPES: Event['event_type'][] = [
  'mode_change',
  'emulation_change',
  'switchover',
  'queue_warning',
  'duplicate',
  'failover',
];

const EVENT_LABELS: Partial<Record<Event['event_type'], string>> = {
  mode_change: 'Mode',
  emulation_change: 'Emulation',
  switchover: 'Switchover',
  queue_warning: 'Queue',
  duplicate: 'Duplicate',
  failover: 'Failover',
};

export function ExperimentActivityPanel({ events, metrics, status }: ExperimentActivityPanelProps) {
  const rows = useMemo(() => {
    const experimentEventRows = [...events]
      .filter((event) => EXPERIMENT_EVENT_TYPES.includes(event.event_type))
      .reverse();

    if (experimentEventRows.length > 0) {
      return experimentEventRows;
    }

    const derivedRows: Event[] = [];

    if (status) {
      derivedRows.push({
        id: -1,
        timestamp: status.timestamp,
        event_type: 'mode_change',
        summary: `Mode: ${EXPERIMENT_MODE_LABELS[status.experiment_mode]}`,
        detail: `Active link ${status.active_link} (${status.decision_reason || 'no decision reason'})`,
        link: status.active_link,
      });
    }

    if (metrics) {
      const switchoverRows = metrics.switchover_events.map((switchover, index) => ({
        id: -10_000 - index,
        timestamp: switchover.ts,
        event_type: 'switchover' as const,
        summary: `Link: ${switchover.from_link}→${switchover.to_link}`,
        detail: `trigger=${switchover.trigger}`,
        link: switchover.to_link,
      }));

      const duplicateRows = metrics.duplicate_events.map((duplicate, index) => ({
        id: -20_000 - index,
        timestamp: duplicate.ts,
        event_type: 'duplicate' as const,
        summary: `Duplicate discarded: ${duplicate.winning_link} beat ${duplicate.late_link}`,
        detail: `seq=${duplicate.sequence_number} gap=${duplicate.duplicate_gap_ms.toFixed(1)} ms`,
        link: duplicate.late_link,
      }));

      derivedRows.push(...switchoverRows, ...duplicateRows);

      if (metrics.queue_overflow_count > 0) {
        derivedRows.push({
          id: -30_000,
          timestamp: status?.timestamp ?? Date.now() / 1000,
          event_type: 'queue_warning',
          summary: 'Queue overflow observed',
          detail: `${metrics.queue_overflow_count} overflow event(s) this session`,
          link: null,
        });
      }
    }

    return derivedRows.sort((a, b) => b.timestamp - a.timestamp).slice(0, 60);
  }, [events, metrics, status]);

  return (
    <Panel title="Experiment Activity" className="events-panel">
      {rows.length === 0 ? (
        <p className="empty-state">No experiment events yet.</p>
      ) : (
        <div className="events-list">
          {rows.map((event) => (
            <article key={event.id} className="event-row">
              <div className={`event-pill event-${event.event_type}`}>
                {EVENT_LABELS[event.event_type] ?? event.event_type}
              </div>

              <div className="event-copy">
                <strong>{event.summary}</strong>
                {event.detail && <p>{event.detail}</p>}
              </div>

              <time dateTime={new Date(event.timestamp * 1000).toISOString()}>
                {formatClockTime(event.timestamp * 1000, {
                  includeMilliseconds: true,
                })}
              </time>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
