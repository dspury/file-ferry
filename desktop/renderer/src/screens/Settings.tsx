/**
 * Settings screen.
 *
 * Edits application settings via `settings.get` / `settings.update`.
 * Per plan §10 Pkg7 step 3, saves are NOT optimistic: the form reflects
 * the persisted result returned by the sidecar, and errors are surfaced.
 * Paths are entered as text (native pickers arrive with the full desktop
 * flow in a later sub-package).
 */
import { useState, type JSX } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import {
  Banner,
  Field,
  Panel,
  LoadingState,
  ScreenError,
  ScreenLoading,
} from '../components/ui.js';
import { validateSettings } from '../lib/settings.js';
import { buildReportText, canCopy, diagnosticFileName } from '../lib/diagnostics.js';
import type { AppSettings } from '../../../shared/ipc-methods.js';

const CODECS = ['ProRes422Proxy', 'H264', 'H265', 'ProRes422HQ', 'ProRes4444'];
const CHECKSUM_ALGOS = ['xxhash64', 'sha256'];
const MODES = ['copy', 'move', 'link'];
const CONFLICTS = ['skip', 'overwrite', 'rename'];

export function Settings(): JSX.Element {
  const loaded = useAsync(() => window.ferry.settings.get());
  // Only the operator's edits are state; the baseline is what the sidecar
  // returned. This used to be one `form` state seeded from an effect
  // (`if (loaded.data !== null && form === null) setForm(loaded.data)`),
  // which is the copy-props-into-state pattern react-hooks 7 flags as
  // `set-state-in-effect`: it renders once with `form === null`, commits,
  // then immediately re-renders with the value. Deriving it needs no effect
  // and no second commit.
  const [edits, setEdits] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const form = edits ?? loaded.data;

  if (loaded.loading) {
    return <ScreenLoading message="Reading saved settings…" />;
  }
  if (loaded.error !== null) {
    return <ScreenError message={loaded.error} onRetry={loaded.reload} />;
  }
  if (form === null) {
    return (
      <ScreenError message="The sidecar returned no settings to edit." onRetry={loaded.reload} />
    );
  }

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setEdits({ ...form, [key]: value });
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
      const updated = await window.ferry.settings.update({
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
      setEdits(updated);
      setSavedMsg('Settings saved.');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <Panel title="Proxy defaults" description="Applied to derivatives generated after an offload">
        <div className="field-grid">
          <Field label="Codec">
            <select value={form.proxyCodec} onChange={(e) => set('proxyCodec', e.target.value)}>
              {CODECS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Proxy height" hint="Pixels; the width follows the source aspect">
            <input
              type="number"
              min={1}
              value={form.proxyHeight}
              onChange={(e) => set('proxyHeight', Number(e.target.value))}
            />
          </Field>
        </div>
      </Panel>

      <Panel
        title="Checksum policy"
        description="How every copy is verified. xxhash64 is fast; sha256 is cryptographic."
      >
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

      <Panel title="Tool paths" description="Override auto-detection when a tool is not on PATH">
        <Field label="ffmpeg path" hint="Leave empty to auto-detect on PATH">
          <input
            value={form.ffmpegPath ?? ''}
            placeholder="/usr/local/bin/ffmpeg"
            onChange={(e) => set('ffmpegPath', e.target.value || null)}
          />
        </Field>
        <Field label="Resolve path" hint="Optional DaVinci Resolve path">
          <input
            value={form.resolvePath ?? ''}
            placeholder="/Applications/DaVinci Resolve"
            onChange={(e) => set('resolvePath', e.target.value || null)}
          />
        </Field>
      </Panel>

      <Panel title="Organization" description="Defaults the Organize screen starts from">
        <Field label="Template" hint="Tokens are expanded per file, e.g. {date}/{camera}">
          <input
            value={form.organizeTemplate}
            onChange={(e) => set('organizeTemplate', e.target.value)}
          />
        </Field>
        <div className="field-grid">
          <Field label="Mode">
            <select value={form.organizeMode} onChange={(e) => set('organizeMode', e.target.value)}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
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
      </Panel>

      {/*
        One save for the whole screen, and it stays put at the bottom of the
        form rather than one per panel — the panels are groupings, not
        separate transactions.
      */}
      <div className="row">
        <button
          type="button"
          className="btn btn--primary"
          onClick={save}
          disabled={saving || !validation.valid}
        >
          {saving ? 'Saving…' : 'Save settings'}
        </button>
      </div>
      {/*
        A disabled Save with the reason set in muted grey beside it put the
        one sentence that explains the disabled button in the quietest type
        on the screen. It is the blocker; it gets banner weight.
      */}
      {validation.valid ? null : (
        <Banner tone="warn" label="Cannot save">
          {validation.errors.join('; ')}
        </Banner>
      )}
      {savedMsg !== null ? <Banner tone="ok">{savedMsg}</Banner> : null}
      {saveError !== null ? <Banner tone="danger">{saveError}</Banner> : null}

      <DiagnosticsPanel />
    </div>
  );
}

function DiagnosticsPanel(): JSX.Element {
  const diag = useAsync(() => window.ferry.app.diagnostics());
  const [copied, setCopied] = useState(false);

  if (diag.loading) {
    return (
      <Panel title="Diagnostics">
        <LoadingState message="Gathering diagnostics…" />
      </Panel>
    );
  }
  if (diag.error !== null) {
    return (
      <Panel title="Diagnostics">
        <Banner tone="warn">Diagnostics unavailable: {diag.error}</Banner>
      </Panel>
    );
  }
  const report = {
    summary: diag.data?.summary ?? '',
    generatedAt: new Date().toISOString(),
    appVersion: 'desktop',
  };
  const text = buildReportText(report);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Panel
      title="Diagnostics"
      description={`Attach this to a bug report. Saves as ${diagnosticFileName(report.generatedAt)}`}
      actions={
        <>
          <button type="button" className="btn btn--sm" onClick={copy} disabled={!canCopy(report)}>
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => void window.ferry.app.openDiagnosticFolder()}
          >
            Open folder
          </button>
        </>
      }
    >
      <pre className="pre">{text}</pre>
    </Panel>
  );
}
