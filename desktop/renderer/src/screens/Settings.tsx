/**
 * Settings screen.
 *
 * Edits application settings via `settings.get` / `settings.update`.
 * Per plan §10 Pkg7 step 3, saves are NOT optimistic: the form reflects
 * the persisted result returned by the sidecar, and errors are surfaced.
 * Paths are entered as text (native pickers arrive with the full desktop
 * flow in a later sub-package).
 */
import { useEffect, useState } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import { Chip, Field, Panel, LoadingState, ErrorState } from '../components/ui.js';
import { validateSettings } from '../lib/settings.js';
import type { AppSettings } from '../../../shared/ipc-methods.js';

const CODECS = ['ProRes422Proxy', 'H264', 'H265', 'ProRes422HQ', 'ProRes4444'];
const CHECKSUM_ALGOS = ['xxhash64', 'sha256'];
const MODES = ['copy', 'move', 'link'];
const CONFLICTS = ['skip', 'overwrite', 'rename'];

export function Settings(): JSX.Element {
  const loaded = useAsync(() => window.mediaMate.settings.get());
  const [form, setForm] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (loaded.data !== null && form === null) {
      setForm(loaded.data);
    }
  }, [loaded.data, form]);

  if (loaded.loading) {
    return <LoadingState message="Loading settings…" />;
  }
  if (loaded.error !== null) {
    return <ErrorState message={loaded.error} />;
  }
  if (form === null) {
    return <ErrorState message="No settings data." />;
  }

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setForm({ ...form, [key]: value });
    setSavedMsg(null);
    setSaveError(null);
  };

  const validation = validateSettings(form);

  const save = async () => {
    if (!validation.valid) {
      setSaveError(validation.errors.join('; '));
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSavedMsg(null);
    try {
      const updated = await window.mediaMate.settings.update({
        proxyCodec: form.proxyCodec,
        proxyHeight: form.proxyHeight,
        checksumAlgo: form.checksumAlgo,
        resolvePath: form.resolvePath,
        ffmpegPath: form.ffmpegPath,
        organizeTemplate: form.organizeTemplate,
        organizeMode: form.organizeMode,
        organizeOnConflict: form.organizeOnConflict,
      });
      // Reflect the persisted result, not an optimistic value.
      setForm(updated);
      setSavedMsg('Saved.');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="stack">
      <h2>Settings</h2>

      <Panel title="Proxy defaults">
        <div className="row">
          <div className="grow">
            <Field label="Codec">
              <select value={form.proxyCodec} onChange={(e) => set('proxyCodec', e.target.value)}>
                {CODECS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grow">
            <Field label="Proxy height">
              <input
                type="number"
                min={1}
                value={form.proxyHeight}
                onChange={(e) => set('proxyHeight', Number(e.target.value))}
              />
            </Field>
          </div>
        </div>
      </Panel>

      <Panel title="Checksum policy">
        <Field label="Checksum algorithm">
          <select value={form.checksumAlgo} onChange={(e) => set('checksumAlgo', e.target.value)}>
            {CHECKSUM_ALGOS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </Field>
      </Panel>

      <Panel title="Tool paths">
        <Field label="ffmpeg path" hint="Leave empty to auto-detect on PATH">
          <input
            value={form.ffmpegPath ?? ''}
            onChange={(e) => set('ffmpegPath', e.target.value || null)}
          />
        </Field>
        <Field label="Resolve path" hint="Optional DaVinci Resolve path">
          <input
            value={form.resolvePath ?? ''}
            onChange={(e) => set('resolvePath', e.target.value || null)}
          />
        </Field>
      </Panel>

      <Panel title="Organization">
        <Field label="Template">
          <input
            value={form.organizeTemplate}
            onChange={(e) => set('organizeTemplate', e.target.value)}
          />
        </Field>
        <div className="row">
          <div className="grow">
            <Field label="Mode">
              <select
                value={form.organizeMode}
                onChange={(e) => set('organizeMode', e.target.value)}
              >
                {MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grow">
            <Field label="On conflict">
              <select
                value={form.organizeOnConflict}
                onChange={(e) => set('organizeOnConflict', e.target.value)}
              >
                {CONFLICTS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>
      </Panel>

      <div className="row">
        <button className="btn btn--primary" onClick={save} disabled={saving || !validation.valid}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        {savedMsg !== null ? <Chip tone="ok">{savedMsg}</Chip> : null}
        {saveError !== null ? <Chip tone="danger">{saveError}</Chip> : null}
      </div>
    </div>
  );
}
