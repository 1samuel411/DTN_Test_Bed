import React, { useState } from 'react';
import { api } from '../../api/client';
import { Panel } from '../../components/Panel';

interface CachedDeviceDataPanelProps {
  onCleared?: () => Promise<void> | void;
}

export function CachedDeviceDataPanel({ onCleared }: CachedDeviceDataPanelProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleClearCachedData = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);

    try {
      await api.sendCommand({ cmd: 'clear_queue' });
      if (onCleared) {
        await onCleared();
      }
      setSuccess('Cleared cached device queue data.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Cached Device Data" className="stack-panel" busy={busy}>
      <p className="panel-footnote">
        Clears queued telemetry on the device so the next experiment starts with an empty device queue.
      </p>

      <div className="button-row">
        <button
          type="button"
          className="button button-secondary button-danger"
          onClick={() => void handleClearCachedData()}
          disabled={busy}
        >
          {busy ? 'Clearing…' : 'Clear Cached Device Data'}
        </button>
      </div>

      {error && <p className="message message-error">{error}</p>}
      {success && <p className="message message-success">{success}</p>}
    </Panel>
  );
}
