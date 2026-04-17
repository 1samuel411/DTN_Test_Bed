import React, { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { Panel } from '../../components/Panel';
import { PiStatusReport } from '../../types';

interface GPSPanelProps {
  status: PiStatusReport | null;
}

const COMMON_BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400];
const COMMON_SEND_FREQUENCIES_HZ = [20, 100, 1000];

export function GPSPanel({ status }: GPSPanelProps) {
  const [baudrate, setBaudrate] = useState('');
  const [sendFrequencyHz, setSendFrequencyHz] = useState('');
  const [busyBaudrate, setBusyBaudrate] = useState(false);
  const [busyFrequency, setBusyFrequency] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const currentSendFrequencyHz =
    typeof status?.gps_send_frequency_hz === 'number'
      ? status.gps_send_frequency_hz
      : null;

  useEffect(() => {
    if (status?.gps_baudrate) {
      setBaudrate(String(status.gps_baudrate));
    }
  }, [status?.gps_baudrate]);

  useEffect(() => {
    if (typeof status?.gps_send_frequency_hz === 'number') {
      setSendFrequencyHz(String(status.gps_send_frequency_hz));
    }
  }, [status?.gps_send_frequency_hz]);

  async function applyBaudrate() {
    const parsed = Number.parseInt(baudrate, 10);

    if (!parsed || parsed < 1200) {
      setError('Choose a valid GPS baudrate before applying.');
      setSuccess(null);
      return;
    }

    setBusyBaudrate(true);
    setError(null);
    setSuccess(null);

    try {
      await api.sendCommand({ cmd: 'set_baudrate', baudrate: parsed });
      setSuccess(`Requested GPS baudrate change to ${parsed}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setBusyBaudrate(false);
    }
  }

  async function applySendFrequency() {
    const normalizedInput = sendFrequencyHz.trim();
    const parsed =
      normalizedInput === '' && currentSendFrequencyHz != null
        ? currentSendFrequencyHz
        : Number.parseFloat(normalizedInput);

    if (!Number.isFinite(parsed) || parsed <= 0 || parsed > 1000) {
      setError('Choose a valid GPS send frequency between 0 and 1000 Hz.');
      setSuccess(null);
      return;
    }

    setBusyFrequency(true);
    setError(null);
    setSuccess(null);

    try {
      await api.sendCommand({ cmd: 'set_gps_send_frequency', hz: parsed });
      setSuccess(`Requested GPS send frequency change to ${parsed} Hz.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setBusyFrequency(false);
    }
  }

  const activeFrequency = Number.parseFloat(sendFrequencyHz);

  return (
    <Panel title="GPS Configuration" className="stack-panel">
      <div className="definition-list">
        <div>
          <span>Status</span>
          <strong className={status?.gps_connected ? 'tone-good' : 'tone-bad'}>
            {status?.gps_connected
              ? `Connected (${status.gps_fix_state})`
              : 'Disconnected'}
          </strong>
        </div>
        <div>
          <span>Device</span>
          <strong>{status?.gps_device ?? 'Unavailable'}</strong>
        </div>
        <div>
          <span>Current baudrate</span>
          <strong>{status?.gps_baudrate ?? 'Unavailable'}</strong>
        </div>
        <div>
          <span>Send frequency</span>
          <strong>{status?.gps_send_frequency_hz ?? 'Unavailable'} Hz</strong>
        </div>
      </div>

      <div className="chip-group">
        {COMMON_BAUDRATES.map((option) => (
          <button
            key={option}
            className={`chip ${baudrate === String(option) ? 'is-active' : ''}`}
            type="button"
            onClick={() => setBaudrate(String(option))}
          >
            {option}
          </button>
        ))}
      </div>

      <div className="button-row button-row-stretch">
        <input
          className="text-input"
          value={baudrate}
          inputMode="numeric"
          placeholder="Custom baudrate"
          onChange={(event) => setBaudrate(event.target.value)}
        />
        <button
          className="button"
          type="button"
          onClick={() => void applyBaudrate()}
          disabled={busyBaudrate}
        >
          {busyBaudrate ? 'Sending…' : 'Apply baudrate'}
        </button>
      </div>

      <div className="chip-group">
        {COMMON_SEND_FREQUENCIES_HZ.map((option) => (
          <button
            key={option}
            className={`chip ${
              Number.isFinite(activeFrequency) && Math.abs(activeFrequency - option) < 0.001
                ? 'is-active'
                : ''
            }`}
            type="button"
            onClick={() => setSendFrequencyHz(String(option))}
          >
            {option} Hz
          </button>
        ))}
      </div>

      <div className="button-row button-row-stretch">
        <input
          className="text-input"
          value={sendFrequencyHz}
          inputMode="decimal"
          placeholder="Send frequency (Hz)"
          onChange={(event) => setSendFrequencyHz(event.target.value)}
          onBlur={() => {
            if (sendFrequencyHz.trim() === '' && currentSendFrequencyHz != null) {
              setSendFrequencyHz(String(currentSendFrequencyHz));
            }
          }}
        />
        <button
          className="button"
          type="button"
          onClick={() => void applySendFrequency()}
          disabled={busyFrequency}
        >
          {busyFrequency ? 'Sending…' : 'Apply frequency'}
        </button>
      </div>

      {error && <p className="message message-error">{error}</p>}
      {success && <p className="message message-success">{success}</p>}
    </Panel>
  );
}
