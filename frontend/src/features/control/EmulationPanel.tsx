import React, { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { Panel } from '../../components/Panel';
import {
  EmulationSettings,
  InterfaceRole,
  PiStatusReport,
} from '../../types';

interface EmulationPanelProps {
  status: PiStatusReport | null;
  onEmulationApplied?: () => void;
  variant?: 'panel' | 'bare';
}

const DEFAULT_SETTINGS: EmulationSettings = {
  delay_ms: 0,
  jitter_ms: 0,
  loss_percent: 0,
  bandwidth_kbps: null,
  outage: false,
};

const INTERFACE_ROLE_OPTIONS: InterfaceRole[] = ['wifi', 'lte', 'both'];

function copySettings(settings: EmulationSettings | null | undefined): EmulationSettings {
  if (!settings) {
    return { ...DEFAULT_SETTINGS };
  }

  return {
    delay_ms: settings.delay_ms,
    jitter_ms: settings.jitter_ms,
    loss_percent: settings.loss_percent,
    bandwidth_kbps: settings.bandwidth_kbps,
    outage: settings.outage,
  };
}

/** Raw kbps string for the bandwidth field; kept separate so values like "12." are not normalized away. */
function parseBandwidthKbpsFromInput(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') {
    return null;
  }
  const parsed = Number.parseFloat(trimmed);
  if (Number.isNaN(parsed)) {
    return null;
  }
  return Math.max(0, parsed);
}

export function EmulationPanel({
  status,
  onEmulationApplied,
  variant = 'panel',
}: EmulationPanelProps) {
  const [interfaceRole, setInterfaceRole] = useState<InterfaceRole>('wifi');
  const [form, setForm] = useState<EmulationSettings>({ ...DEFAULT_SETTINGS });
  const [bandwidthText, setBandwidthText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const activeSettings = useMemo(
    () => {
      if (interfaceRole === 'wifi') {
        return status?.emulation_wifi;
      }

      if (interfaceRole === 'lte') {
        return status?.emulation_lte;
      }

      return null;
    },
    [interfaceRole, status?.emulation_wifi, status?.emulation_lte],
  );

  useEffect(() => {
    const next = copySettings(activeSettings);
    setForm(next);
    setBandwidthText(
      next.bandwidth_kbps == null ? '' : String(next.bandwidth_kbps),
    );
  }, [activeSettings, interfaceRole]);

  const handleBandwidthChange = (event: ChangeEvent<HTMLInputElement>) => {
    const raw = event.target.value;
    if (raw !== '' && !/^\d*\.?\d*$/.test(raw)) {
      return;
    }
    setBandwidthText(raw);
    setForm((current) => ({
      ...current,
      bandwidth_kbps: parseBandwidthKbpsFromInput(raw),
    }));
  };

  function setNumberField(
    key: keyof Pick<
      EmulationSettings,
      'delay_ms' | 'jitter_ms' | 'loss_percent'
    >,
    value: string,
  ) {
    setForm((current) => {
      if (key === 'loss_percent') {
        return {
          ...current,
          loss_percent: Number.parseFloat(value) || 0,
        };
      }

      return {
        ...current,
        [key]: Number.parseInt(value, 10) || 0,
      };
    });
  }

  async function send(command: 'set_emulation' | 'revert_emulation') {
    setBusy(true);
    setError(null);
    setSuccess(null);

    try {
      if (command === 'set_emulation') {
        await api.sendCommand({
          cmd: 'set_emulation',
          interface_role: interfaceRole,
          settings: form,
        });
        onEmulationApplied?.();
        setSuccess(
          interfaceRole === 'both'
            ? 'Applied WiFi + LTE emulation profile.'
            : `Applied ${interfaceRole.toUpperCase()} emulation profile.`,
        );
      } else {
        await api.sendCommand({
          cmd: 'revert_emulation',
          interface_role: interfaceRole,
        });
        setForm({ ...DEFAULT_SETTINGS });
        setBandwidthText('');
        setSuccess(
          interfaceRole === 'both'
            ? 'Reverted WiFi + LTE emulation profile.'
            : `Reverted ${interfaceRole.toUpperCase()} emulation profile.`,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setBusy(false);
    }
  }

  const body = (
    <>
      <div className="segmented segmented--three">
        {INTERFACE_ROLE_OPTIONS.map((role) => (
          <button
            key={role}
            className={`segmented-button ${
              interfaceRole === role ? 'is-active' : ''
            }`}
            type="button"
            onClick={() => setInterfaceRole(role)}
          >
            {role === 'both' ? 'BOTH' : role.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="info-block">
        <span className="info-label">Active on Pi</span>
        {interfaceRole === 'both' ? (
          <>
            <strong>
              WiFi: delay {status?.emulation_wifi?.delay_ms ?? 0} ms, jitter{' '}
              {status?.emulation_wifi?.jitter_ms ?? 0} ms, loss{' '}
              {status?.emulation_wifi?.loss_percent ?? 0}%, bandwidth{' '}
              {status?.emulation_wifi?.bandwidth_kbps ?? 'unlimited'} kbps
              {status?.emulation_wifi?.outage ? ', outage enabled' : ''}
            </strong>
            <strong>
              LTE: delay {status?.emulation_lte?.delay_ms ?? 0} ms, jitter{' '}
              {status?.emulation_lte?.jitter_ms ?? 0} ms, loss{' '}
              {status?.emulation_lte?.loss_percent ?? 0}%, bandwidth{' '}
              {status?.emulation_lte?.bandwidth_kbps ?? 'unlimited'} kbps
              {status?.emulation_lte?.outage ? ', outage enabled' : ''}
            </strong>
          </>
        ) : (
          <strong>
            delay {activeSettings?.delay_ms ?? 0} ms, jitter{' '}
            {activeSettings?.jitter_ms ?? 0} ms, loss{' '}
            {activeSettings?.loss_percent ?? 0}%, bandwidth{' '}
            {activeSettings?.bandwidth_kbps ?? 'unlimited'} kbps
            {activeSettings?.outage ? ', outage enabled' : ''}
          </strong>
        )}
      </div>

      <div className="form-grid">
        <label className="field">
          <span>Delay (ms)</span>
          <input
            value={String(form.delay_ms)}
            inputMode="numeric"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setNumberField('delay_ms', event.target.value)
            }
          />
        </label>

        <label className="field">
          <span>Jitter (ms)</span>
          <input
            value={String(form.jitter_ms)}
            inputMode="numeric"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setNumberField('jitter_ms', event.target.value)
            }
          />
        </label>

        <label className="field">
          <span>Loss (%)</span>
          <input
            value={String(form.loss_percent)}
            inputMode="decimal"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setNumberField('loss_percent', event.target.value)
            }
          />
        </label>

        <label className="field">
          <span>Bandwidth (kbps)</span>
          <input
            value={bandwidthText}
            inputMode="decimal"
            step="any"
            placeholder="Unlimited"
            onChange={handleBandwidthChange}
          />
        </label>
      </div>

      <label className="toggle-field">
        <input
          type="checkbox"
          checked={form.outage}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              outage: event.target.checked,
            }))
          }
        />
        <span>Force outage state</span>
      </label>

      <div className="button-row">
        <button
          className="button"
          type="button"
          onClick={() => void send('set_emulation')}
          disabled={busy}
        >
          {busy ? 'Sending…' : 'Apply profile'}
        </button>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => void send('revert_emulation')}
          disabled={busy}
        >
          Revert profile
        </button>
      </div>

      {error && <p className="message message-error">{error}</p>}
      {success && <p className="message message-success">{success}</p>}
    </>
  );

  if (variant === 'bare') {
    return (
      <div className="emulation-panel emulation-panel--bare" aria-busy={busy}>
        {body}
      </div>
    );
  }

  return (
    <Panel title="Network Emulation" className="stack-panel">
      {body}
    </Panel>
  );
}
