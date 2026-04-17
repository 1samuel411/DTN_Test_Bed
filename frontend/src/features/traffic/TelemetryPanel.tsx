import React, { useEffect, useMemo, useState } from 'react';
import { Panel } from '../../components/Panel';
import { formatBytes, formatClockTime } from '../../lib/format';
import { AltitudeTelemetry } from '../../types';

interface TelemetryPanelProps {
  telemetry: AltitudeTelemetry[];
}

type RangeKey = '30s' | '2m' | '5m' | '10m' | 'all';
type ViewMode = 'graph' | 'table';

const RANGE_OPTIONS: Array<{ key: RangeKey; label: string; ms: number | null }> = [
  { key: '30s', label: '30s', ms: 30_000 },
  { key: '2m', label: '2m', ms: 2 * 60_000 },
  { key: '5m', label: '5m', ms: 5 * 60_000 },
  { key: '10m', label: '10m', ms: 10 * 60_000 },
  { key: 'all', label: 'All time', ms: null },
];

const SVG_WIDTH = 1000;
const SVG_HEIGHT = 300;
const GRAPH_PADDING_X = 86;
const GRAPH_PADDING_Y = 22;
const GRAPH_INNER_WIDTH = SVG_WIDTH - GRAPH_PADDING_X * 2;
const GRAPH_INNER_HEIGHT = SVG_HEIGHT - GRAPH_PADDING_Y * 2;
const CLOCK_SKEW_TOLERANCE_MS = 60_000;

function telemetryKey(sample: AltitudeTelemetry): string {
  if (sample.packet_id) {
    return sample.packet_id;
  }
  return `${sample.timestamp}-${sample.sequence_number}`;
}

export function TelemetryPanel({ telemetry }: TelemetryPanelProps) {
  const [range, setRange] = useState<RangeKey>('30s');
  const [view, setView] = useState<ViewMode>('graph');
  const [nowMs, setNowMs] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 250);
    return () => window.clearInterval(timer);
  }, []);

  const samples = useMemo(
    () =>
      [...telemetry].sort((a, b) => {
        if (a.timestamp === b.timestamp) {
          return a.sequence_number - b.sequence_number;
        }
        return a.timestamp - b.timestamp;
      }),
    [telemetry],
  );

  const rangeWindow = RANGE_OPTIONS.find((option) => option.key === range) ?? RANGE_OPTIONS[0];
  const firstTimestampMs = samples.length > 0 ? samples[0].timestamp * 1000 : nowMs;
  const latestTimestampMs = samples.length > 0 ? samples[samples.length - 1].timestamp * 1000 : nowMs;
  const clockSkewMs = Math.abs(nowMs - latestTimestampMs);
  const timelineNowMs =
    samples.length === 0 || clockSkewMs <= CLOCK_SKEW_TOLERANCE_MS ? nowMs : latestTimestampMs;
  const startMs = rangeWindow.ms == null ? firstTimestampMs : timelineNowMs - rangeWindow.ms;

  const visibleSamples = useMemo(
    () => samples.filter((sample) => sample.timestamp * 1000 >= startMs),
    [samples, startMs],
  );

  const graphSamples = visibleSamples.length > 0 ? visibleSamples : samples.slice(-1);
  const xStartMs = rangeWindow.ms == null ? firstTimestampMs : startMs;
  const xEndMs = rangeWindow.ms == null ? Math.max(timelineNowMs, firstTimestampMs) : timelineNowMs;
  const xSpanMs = Math.max(1, xEndMs - xStartMs);

  const altitudeValues = graphSamples.map((sample) => sample.altitude);
  const rawMinY = altitudeValues.length > 0 ? Math.min(...altitudeValues) : 0;
  const rawMaxY = altitudeValues.length > 0 ? Math.max(...altitudeValues) : 1;
  const ySpan = rawMaxY - rawMinY;
  const minY = ySpan === 0 ? rawMinY - 0.5 : rawMinY;
  const maxY = ySpan === 0 ? rawMaxY + 0.5 : rawMaxY;
  const yScale = Math.max(1, maxY - minY);
  const yTicks = [rawMaxY, (rawMinY + rawMaxY) / 2, rawMinY];

  const linePath = graphSamples
    .map((sample, index) => {
      const x =
        GRAPH_PADDING_X + (((sample.timestamp * 1000 - xStartMs) / xSpanMs) * GRAPH_INNER_WIDTH);
      const y = GRAPH_PADDING_Y + (1 - (sample.altitude - minY) / yScale) * GRAPH_INNER_HEIGHT;
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  const tableRows = useMemo(() => [...samples].reverse(), [samples]);

  return (
    <Panel title="Telemetry Stream" className="traffic-panel telemetry-panel">
      <div className="telemetry-toolbar" role="group" aria-label="Telemetry view controls">
        <div className="chip-group telemetry-range-group">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`chip ${range === option.key ? 'is-active' : ''}`}
              onClick={() => setRange(option.key)}
              aria-pressed={range === option.key}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="segmented telemetry-view-toggle" role="group" aria-label="Chart or table view">
          <button
            type="button"
            className={`segmented-button ${view === 'graph' ? 'is-active' : ''}`}
            onClick={() => setView('graph')}
            aria-pressed={view === 'graph'}
          >
            Chart
          </button>
          <button
            type="button"
            className={`segmented-button ${view === 'table' ? 'is-active' : ''}`}
            onClick={() => setView('table')}
            aria-pressed={view === 'table'}
          >
            Table
          </button>
        </div>
      </div>

      {view === 'graph' && (
        <div className="telemetry-graph-wrap">
          {visibleSamples.length === 0 ? (
            <p className="empty-state">No telemetry samples in the selected time window yet.</p>
          ) : (
            <>
              <svg
                className="telemetry-graph"
                viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
                role="img"
                aria-label={`Altitude graph for ${rangeWindow.label} window`}
              >
                <rect
                  x={GRAPH_PADDING_X}
                  y={GRAPH_PADDING_Y}
                  width={GRAPH_INNER_WIDTH}
                  height={GRAPH_INNER_HEIGHT}
                  className="telemetry-plot-bg"
                />
                {yTicks.map((tickValue) => {
                  const y =
                    GRAPH_PADDING_Y +
                    (1 - (tickValue - minY) / yScale) * GRAPH_INNER_HEIGHT;
                  return (
                    <g key={tickValue}>
                      <line
                        x1={GRAPH_PADDING_X}
                        y1={y}
                        x2={GRAPH_PADDING_X + GRAPH_INNER_WIDTH}
                        y2={y}
                        className="telemetry-grid-line"
                      />
                      <text
                        x={GRAPH_PADDING_X - 12}
                        y={y + 4}
                        textAnchor="end"
                        className="telemetry-y-label"
                      >
                        {tickValue.toFixed(1)}m
                      </text>
                    </g>
                  );
                })}
                <line
                  x1={GRAPH_PADDING_X}
                  y1={GRAPH_PADDING_Y}
                  x2={GRAPH_PADDING_X}
                  y2={GRAPH_PADDING_Y + GRAPH_INNER_HEIGHT}
                  className="telemetry-axis-line"
                />
                <path d={linePath} className="telemetry-line" />
              </svg>
              <div className="telemetry-graph-axes">
                <span>{formatClockTime(xStartMs)}</span>
                <span>{formatClockTime(xStartMs + xSpanMs / 2)}</span>
                <span>{formatClockTime(xEndMs)}</span>
              </div>
              <div className="telemetry-graph-stats">
                <span>Samples: {visibleSamples.length}</span>
                <span>
                  Altitude range: {rawMinY.toFixed(1)}m → {rawMaxY.toFixed(1)}m
                </span>
              </div>
            </>
          )}
        </div>
      )}
      {view === 'table' && (
        <div className="telemetry-table-wrap">
          {tableRows.length === 0 ? (
            <p className="empty-state">No telemetry samples recorded yet.</p>
          ) : (
            <>
              <p className="panel-footnote">Showing all {tableRows.length} telemetry samples.</p>
              <div className="telemetry-table-scroll">
                <table className="telemetry-table">
                  <thead>
                    <tr>
                      <th>Send time</th>
                      <th>Transmit time (ms)</th>
                      <th>Seq</th>
                      <th>Altitude (m)</th>
                      <th>Payload size</th>
                      <th>Link</th>
                      <th>Queue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((sample) => (
                      <tr key={telemetryKey(sample)}>
                        <td>{formatClockTime(sample.timestamp * 1000, { includeMilliseconds: true })}</td>
                        <td>
                          {sample.receive_timestamp
                            ? `${Math.max(0, (sample.receive_timestamp - sample.timestamp) * 1000).toFixed(1)}`
                            : '—'}
                        </td>
                        <td>{sample.sequence_number}</td>
                        <td>{sample.altitude.toFixed(2)}</td>
                        <td>
                          {sample.payload_size_bytes != null
                            ? formatBytes(sample.payload_size_bytes)
                            : '—'}
                        </td>
                        <td>{sample.send_link || sample.active_link}</td>
                        <td>{sample.queue_depth}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
