/**
 * Organize screen.
 *
 * Existing-media adoption following plan -> review -> execute -> verify ->
 * receipt (plan §4.3). Select a source, pick an org profile, preview the
 * target tree (never mutating), decide collisions, then apply. A move
 * requires explicit confirmation; nothing is optimistic.
 */
import { useState } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import {
  Banner,
  Chip,
  EmptyState,
  Field,
  Panel,
  PathCell,
  PathPicker,
  Steps,
  type StepDef,
} from '../components/ui.js';
import { ConfirmDialog } from '../components/ConfirmDialog.js';
import {
  organizeStage,
  previewApplyable,
  collisionBlocks,
  moveRequiresConfirm,
  outcomeSummary,
  profileLabel,
  collisionCount,
} from '../lib/organize.js';
import type { OrganizePreview, OrganizationProfile } from '../../../shared/ipc-methods.js';

const PREVIEW_ROWS = 100;

const STEPS: readonly StepDef[] = [
  { id: 'source', label: 'Source' },
  { id: 'preview', label: 'Profile' },
  { id: 'ready', label: 'Review' },
  { id: 'running', label: 'Apply' },
  { id: 'done', label: 'Done' },
];

/*
 * Copy and link leave the source intact; move does not. Saying so next to
 * the choice — rather than only in the confirm dialog after the fact — is
 * what stops the wrong one being picked.
 */
const MODE_NOTE = {
  copy: 'Source files are left untouched.',
  move: 'Source files are removed after a successful write. Destructive.',
  link: 'No bytes are copied; the destination points at the source.',
} satisfies Record<'copy' | 'move' | 'link', string>;

export function Organize(): JSX.Element {
  const profiles = useAsync(() => window.ferry.profile.list());

  const [sourcePath, setSourcePath] = useState<string | null>(null);
  const [destRoot, setDestRoot] = useState<string | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [mode, setMode] = useState<'copy' | 'move' | 'link'>('copy');
  const [confirmMove, setConfirmMove] = useState(false);

  const [preview, setPreview] = useState<OrganizePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [outcome, setOutcome] = useState<ReturnType<typeof outcomeSummary> | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const pickSource = async () => {
    const r = await window.ferry.dialog.pick({ kind: 'directory' });
    if (!r.cancelled && r.path) {
      setSourcePath(r.path);
      setPreview(null);
    }
  };

  const pickDest = async () => {
    const r = await window.ferry.dialog.pick({ kind: 'directory' });
    if (!r.cancelled && r.path) {
      setDestRoot(r.path);
      setPreview(null);
    }
  };

  const selectedProfile = profiles.data?.profiles.find((p) => p.id === profileId) ?? null;

  const buildPreview = async () => {
    if (!sourcePath || !destRoot) return;
    setPreviewing(true);
    setPreviewError(null);
    setPreview(null);
    try {
      // Inspect the source read-only, then preview the target tree.
      const inspected = await window.ferry.source.inspect({
        path: sourcePath,
        kind: 'existing_media',
      });
      const baseParams = {
        sourceRoot: sourcePath,
        destRoot,
        entries: inspected.entries,
        mode,
      };
      // `template` is optional; add it only when a profile is selected.
      const previewParams = selectedProfile
        ? { ...baseParams, template: selectedProfile.template }
        : baseParams;
      const p = await window.ferry.organize.preview(previewParams);
      setPreview(p);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewing(false);
    }
  };

  const apply = async () => {
    if (!preview || !sourcePath || !destRoot) return;
    if (collisionBlocks(preview)) {
      setApplyError('Resolve collisions before applying.');
      return;
    }
    if (moveRequiresConfirm(mode, confirmMove)) {
      setApplyError('Move requires explicit confirmation.');
      return;
    }
    setApplying(true);
    setApplyError(null);
    try {
      const inspected = await window.ferry.source.inspect({
        path: sourcePath,
        kind: 'existing_media',
      });
      const baseParams = {
        sourceRoot: sourcePath,
        destRoot,
        entries: inspected.entries,
        mode,
      };
      // Both fields are optional; each is added only when it applies.
      const withTemplate = selectedProfile
        ? { ...baseParams, template: selectedProfile.template }
        : baseParams;
      const applyParams = mode === 'move' ? { ...withTemplate, confirmMove } : withTemplate;
      const result = await window.ferry.organize.apply(applyParams);
      setOutcome(outcomeSummary(result.entries));
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  };

  const stage = organizeStage({
    sourceEntries: preview?.entries.length ?? 0,
    preview,
    executing: applying,
    done: outcome !== null,
  });

  const hidden = preview === null ? 0 : Math.max(0, preview.entries.length - PREVIEW_ROWS);

  return (
    <div className="page">
      <Steps label="Organize progress" steps={STEPS} activeId={stage} />

      <Panel
        title="Source & destination"
        description="Existing media to reorganize, and the root the new structure is written under."
      >
        <div className="field-grid">
          <Field label="Source folder">
            <PathPicker value={sourcePath} onPick={pickSource} buttonLabel="Browse…" />
          </Field>
          <Field label="Destination root">
            <PathPicker
              value={destRoot}
              onPick={pickDest}
              disabled={!sourcePath}
              buttonLabel="Browse…"
            />
          </Field>
        </div>
      </Panel>

      <Panel
        title="Organization profile"
        description="The profile decides the folder template; the mode decides what happens to the originals."
      >
        <div className="field-grid">
          <Field label="Profile">
            <select
              value={profileId ?? ''}
              onChange={(e) => setProfileId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Use default template</option>
              {(profiles.data?.profiles ?? []).map((p: OrganizationProfile) => (
                <option key={p.id} value={p.id}>
                  {profileLabel(p)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Mode" hint={MODE_NOTE[mode]}>
            <select
              value={mode}
              onChange={(e) => {
                // SAFETY: a <select> can only emit one of its own <option>
                // values, and the three below are exactly the members of
                // `mode`.
                setMode(e.target.value as typeof mode);
              }}
            >
              <option value="copy">Copy</option>
              <option value="move">Move</option>
              <option value="link">Link</option>
            </select>
          </Field>
        </div>

        {mode === 'move' ? (
          <>
            <Banner tone="warn" label="Destructive">
              Move deletes each source file once its copy is written and verified. ferry cannot undo
              it.
            </Banner>
            <label className="checkline">
              <input
                type="checkbox"
                checked={confirmMove}
                onChange={(e) => setConfirmMove(e.target.checked)}
              />
              I understand the source files will be moved
            </label>
          </>
        ) : null}

        <div className="form-actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={buildPreview}
            disabled={!sourcePath || !destRoot || previewing}
          >
            {previewing ? 'Previewing…' : 'Preview target tree'}
          </button>
        </div>
        {previewError !== null ? <Banner tone="danger">{previewError}</Banner> : null}
      </Panel>

      <Panel
        title="Review preview"
        description="A preview never touches the filesystem."
        flush={preview !== null}
        actions={
          preview === null ? undefined : (
            <>
              {preview.collisions.length > 0 ? (
                <Chip tone="danger">{collisionCount(preview.collisions)} collisions</Chip>
              ) : (
                <Chip tone="ok">No collisions</Chip>
              )}
              <span className="muted">
                {preview.entries.length.toLocaleString()} files · {preview.mode}
              </span>
            </>
          )
        }
      >
        {preview === null ? (
          <EmptyState
            message="No preview yet"
            hint="Choose a source and destination, then preview to see the exact target tree."
          />
        ) : (
          <>
            <div className="table-wrap table-wrap--short">
              <table className="table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Destination</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.entries.slice(0, PREVIEW_ROWS).map((e) => (
                    <tr key={e.sourcePath}>
                      <td>
                        <PathCell path={e.sourcePath} />
                      </td>
                      <td>
                        <PathCell path={e.destPath} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {hidden > 0 ? (
              <div className="card__footer muted">
                Showing the first {PREVIEW_ROWS} of {preview.entries.length.toLocaleString()} files
                · {hidden.toLocaleString()} more not listed
              </div>
            ) : null}
          </>
        )}
      </Panel>

      <Panel title="Apply" description="The first step that writes to disk.">
        <div className="row">
          <button
            type="button"
            className={mode === 'move' ? 'btn btn--danger' : 'btn btn--primary'}
            onClick={() => (mode === 'move' ? setConfirmOpen(true) : apply())}
            disabled={
              !previewApplyable(preview) ||
              moveRequiresConfirm(mode, confirmMove) ||
              applying ||
              outcome !== null
            }
          >
            {applying ? 'Applying…' : outcome !== null ? 'Done' : `Apply (${mode})`}
          </button>
        </div>
        {applyError !== null ? <Banner tone="danger">{applyError}</Banner> : null}
        {outcome !== null ? (
          <Banner tone={outcome.failed > 0 ? 'warn' : 'ok'} label="Result">
            {outcome.ok.toLocaleString()} of {outcome.total.toLocaleString()} entries written
            {outcome.failed > 0 ? `, ${outcome.failed.toLocaleString()} failed` : ''}.
          </Banner>
        ) : null}
      </Panel>

      {confirmOpen ? (
        <ConfirmDialog
          title="Move files"
          body="This will move source files into the destination. This is destructive and cannot be undone by ferry."
          phrase="move"
          confirmLabel="Move files"
          onConfirm={() => {
            setConfirmOpen(false);
            setConfirmMove(true);
            void apply();
          }}
          onCancel={() => setConfirmOpen(false)}
        />
      ) : null}
    </div>
  );
}
