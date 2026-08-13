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
import { Chip, Panel, Field } from '../components/ui.js';
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

export function Organize(): JSX.Element {
  const profiles = useAsync(() => window.mediaMate.profile.list());

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

  const pickSource = async () => {
    const r = await window.mediaMate.dialog.pick({ kind: 'directory' });
    if (!r.cancelled && r.path) {
      setSourcePath(r.path);
      setPreview(null);
    }
  };

  const pickDest = async () => {
    const r = await window.mediaMate.dialog.pick({ kind: 'directory' });
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
      const inspected = await window.mediaMate.source.inspect({
        path: sourcePath,
        kind: 'existing_media',
      });
      const previewParams = {
        sourceRoot: sourcePath,
        destRoot,
        entries: inspected.entries,
        mode,
        ...(selectedProfile ? { template: selectedProfile.template } : {}),
      };
      const p = await window.mediaMate.organize.preview(previewParams);
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
      const inspected = await window.mediaMate.source.inspect({
        path: sourcePath,
        kind: 'existing_media',
      });
      const applyParams = {
        sourceRoot: sourcePath,
        destRoot,
        entries: inspected.entries,
        mode,
        ...(selectedProfile ? { template: selectedProfile.template } : {}),
        ...(mode === 'move' ? { confirmMove } : {}),
      };
      const result = await window.mediaMate.organize.apply(applyParams);
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

  return (
    <div className="stack">
      <h2>Organize</h2>
      <p className="muted">Stage: {stage}</p>

      <Panel title="1 · Source & destination">
        <div className="row">
          <button className="btn" onClick={pickSource}>
            Choose source folder
          </button>
          <span className="muted grow">{sourcePath ?? 'none'}</span>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn" onClick={pickDest} disabled={!sourcePath}>
            Choose destination
          </button>
          <span className="muted grow">{destRoot ?? 'none'}</span>
        </div>
      </Panel>

      <Panel title="2 · Organization profile">
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
        <Field label="Mode">
          <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="copy">copy</option>
            <option value="move">move (requires confirm)</option>
            <option value="link">link</option>
          </select>
        </Field>
        {mode === 'move' ? (
          <label className="row" style={{ gap: 6 }}>
            <input
              type="checkbox"
              checked={confirmMove}
              onChange={(e) => setConfirmMove(e.target.checked)}
            />
            Confirm move (source files will be moved)
          </label>
        ) : null}
        <div className="row" style={{ marginTop: 8 }}>
          <button
            className="btn btn--primary"
            onClick={buildPreview}
            disabled={!sourcePath || !destRoot || previewing}
          >
            {previewing ? 'Previewing…' : 'Preview target tree'}
          </button>
        </div>
        {previewError !== null ? <Chip tone="danger">{previewError}</Chip> : null}
      </Panel>

      <Panel title="3 · Review preview">
        {preview === null ? (
          <p className="muted">Build a preview to review the target tree.</p>
        ) : (
          <>
            <p>
              <span className="muted">
                {preview.entries.length} files · mode {preview.mode}
              </span>
            </p>
            {preview.collisions.length > 0 ? (
              <p>
                <Chip tone="danger">
                  {collisionCount(preview.collisions)} collision(s) — resolve before applying
                </Chip>
              </p>
            ) : (
              <p>
                <Chip tone="ok">No collisions</Chip>
              </p>
            )}
            <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: 8 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Destination</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.entries.slice(0, 100).map((e) => (
                    <tr key={e.sourcePath}>
                      <td className="muted">{e.sourcePath}</td>
                      <td className="muted">{e.destPath}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Panel>

      <Panel title="4 · Apply">
        <button
          className="btn btn--primary"
          onClick={apply}
          disabled={
            !previewApplyable(preview) ||
            moveRequiresConfirm(mode, confirmMove) ||
            applying ||
            outcome !== null
          }
        >
          {applying ? 'Applying…' : outcome !== null ? 'Done' : `Apply (${mode})`}
        </button>
        {applyError !== null ? <Chip tone="danger">{applyError}</Chip> : null}
        {outcome !== null ? (
          <p>
            <Chip tone="ok">
              {outcome.ok} ok · {outcome.failed} failed
            </Chip>
          </p>
        ) : null}
      </Panel>
    </div>
  );
}
