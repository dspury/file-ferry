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
  outcomeTone,
  applyStageMark,
  organizePrimary,
  profileLabel,
  collisionCount,
} from '../lib/organize.js';
import type { OrganizePreview, OrganizationProfile } from '../../../shared/ipc-methods.js';

const PREVIEW_ROWS = 100;

const STEPS: readonly StepDef[] = [
  { id: 'source', label: 'Source' },
  { id: 'preview', label: 'Profile' },
  { id: 'ready', label: 'Review' },
  // A preview never touches the filesystem; Apply is the first stage that
  // does, and in move mode it is also the stage that deletes originals.
  { id: 'running', label: 'Apply', writes: true },
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
  /*
   * The last stage is named after what the apply returned, not after having
   * reached it: `DONE` only on a clean run, `INCOMPLETE` when some entries
   * failed, `FAILED` when none landed. Overriding the label here rather than
   * inside `Steps` keeps the rail a dumb renderer of whatever sequence it is
   * handed.
   */
  const outcomeMark = applyStageMark(outcome);
  const steps = STEPS.map((step) =>
    step.id === 'done' ? { ...step, label: outcomeMark.label } : step,
  );
  const primary = organizePrimary(stage);

  const hidden = preview === null ? 0 : Math.max(0, preview.entries.length - PREVIEW_ROWS);

  return (
    <div className="page">
      {/*
        The result goes at the top of the page, above the rail.

        It used to live at the bottom of the panel that produced it, which on
        this screen is 1053px down a 1141px page -- below the fold at both
        1280x800 and 1440x900. An operator who did not scroll saw a stage
        rail and a green NO COLLISIONS chip after a write that had partially
        failed. The banners were already saying exactly the right thing; the
        only thing wrong with them was where they were.
      */}
      {outcome !== null ? (
        <div className="stack">
          <Banner tone={outcomeTone(outcome)} label="Result">
            {outcome.ok.toLocaleString()} of {outcome.total.toLocaleString()} entries written
            {outcome.failed > 0 ? `, ${outcome.failed.toLocaleString()} failed` : ''}.
          </Banner>
          {outcome.failed > 0 ? (
            <Banner tone="warn" label="Incomplete">
              {mode === 'move'
                ? 'The sources behind the failed entries have not been removed. Check them before deleting anything by hand.'
                : 'The sources behind the failed entries are untouched. Nothing was lost; re-run once the cause is cleared.'}
            </Banner>
          ) : null}
        </div>
      ) : null}

      <Steps
        label="Organize progress"
        steps={steps}
        activeId={stage}
        activeTone={outcomeMark.tone}
      />

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
              it. If this source is a camera card that has not been offloaded, use Offload instead —
              it keeps the original and writes a receipt.
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
          {/*
            Filled accent only while previewing is the next thing to do.
            Once a preview exists this is a legitimate but secondary action --
            re-previewing after changing the profile or the mode -- and it
            stays enabled, because a preview never touches the filesystem.
          */}
          <button
            type="button"
            className={primary === 'preview' ? 'btn btn--primary' : 'btn'}
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
            hint="Choose a source and a destination root above, then preview. The preview is read-only — it shows the exact target tree without creating any of it."
          />
        ) : (
          <>
            {preview.collisions.length > 0 ? (
              <div className="card__body">
                {/*
                  Collisions hard-block Apply (`collisionBlocks`), and the
                  only account of that was a chip in the panel header
                  counting them. Ingest already banners the same condition;
                  the screen that refuses to run on it should say more, not
                  less.
                */}
                <Banner tone="danger" label="Collisions">
                  {collisionCount(preview.collisions).toLocaleString()} file(s) would land on a path
                  that another file in this run also claims. Apply stays disabled until that is
                  resolved — change the profile template so the names differ, or set the conflict
                  policy to rename.
                </Banner>
              </div>
            ) : null}
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
          {/*
            Move keeps the danger outline it has always had -- a destructive
            action is not the accent -- so in move mode this row carries no
            filled primary at all, which is the intended reading.

            Spent, the button wears the outcome's own word rather than
            `Done`: it is the control the operator was looking at when the
            apply returned, and it was reporting a clean finish on a run that
            lost a file, the same claim the rail was making.
          */}
          <button
            type="button"
            className={
              mode === 'move'
                ? 'btn btn--danger'
                : primary === 'apply' && outcome === null
                  ? 'btn btn--primary'
                  : 'btn'
            }
            onClick={() => (mode === 'move' ? setConfirmOpen(true) : apply())}
            disabled={
              !previewApplyable(preview) ||
              moveRequiresConfirm(mode, confirmMove) ||
              applying ||
              outcome !== null
            }
          >
            {applying ? 'Applying…' : outcome !== null ? outcomeMark.label : `Apply (${mode})`}
          </button>
        </div>
        {applyError !== null ? <Banner tone="danger">{applyError}</Banner> : null}
      </Panel>

      {confirmOpen ? (
        <ConfirmDialog
          title="Move files"
          body="Each source file is deleted once its copy is written and verified. This cannot be undone by ferry, and there is no second copy of a moved file until this run finishes."
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
