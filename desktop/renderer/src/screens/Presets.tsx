/**
 * Presets screen.
 *
 * A preset is an immutable *revision history*, not a mutable document:
 * `saveRevision` appends, and a destination stays pinned to the revision
 * it was saved with — a newer revision never re-routes an existing
 * destination on its own (spec §4.2). The editor therefore never edits in
 * place: it seeds from the selected revision, and saving produces a new
 * one whose hash is shown.
 *
 * Rules are authored through form controls, not JSON (spec §8.3). A rule's
 * match conditions are exactly what the engine supports — path glob,
 * extensions, categories, source label — and an empty field means "does
 * not constrain".
 */
import { useState, type JSX } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import {
  Banner,
  Chip,
  EmptyState,
  Field,
  LoadingState,
  Panel,
  ScreenError,
  ScreenLoading,
} from '../components/ui.js';
import type {
  PresetContent,
  PresetMatchConditions,
  PresetRevisionDetail,
} from '../../../shared/ipc-methods.js';

const CONFLICT_POLICIES = ['keep_both', 'skip_identical', 'needs_review'] as const;

/** Small deterministic sample the fallback preview routes. */
const SAMPLE_ENTRIES = [
  { path: 'DCIM/100/A001.mov', size: 1, mtime: 0 },
  { path: 'DCIM/100/A002.mov', size: 1, mtime: 0 },
  { path: 'DCIM/100/STILL_0001.png', size: 1, mtime: 0 },
  { path: 'notes.txt', size: 1, mtime: 0 },
] as const;

const ENGINE_DEFAULT_FALLBACK = 'Sources/{source_label}/{relative_dir}/{filename}';

/** One editable rule / group / exclusion row's match conditions. */
interface MatchDraft {
  readonly pathGlob: string;
  readonly extensions: string;
  readonly categories: string;
  readonly sourceLabel: string;
}

interface RouteDraft extends MatchDraft {
  readonly id: string;
  readonly destination: string;
}

interface ExclusionDraft extends MatchDraft {
  readonly id: string;
  readonly reason: string;
}

const EMPTY_MATCH: MatchDraft = { pathGlob: '', extensions: '', categories: '', sourceLabel: '' };

/** What the revision editor holds while it is being authored. */
interface Draft {
  readonly description: string;
  readonly fallbackTemplate: string;
  readonly conflictPolicy: PresetContent['conflictPolicy'];
  readonly rules: readonly RouteDraft[];
  readonly groups: readonly RouteDraft[];
  readonly exclusions: readonly ExclusionDraft[];
}

function parseMatch(m: MatchDraft): PresetMatchConditions {
  const list = (csv: string): readonly string[] | null => {
    const parts = csv
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s !== '');
    return parts.length === 0 ? null : parts;
  };
  return {
    pathGlob: m.pathGlob.trim() === '' ? null : m.pathGlob.trim(),
    extensions: list(m.extensions),
    categories: list(m.categories),
    sourceLabel: m.sourceLabel.trim() === '' ? null : m.sourceLabel.trim(),
  };
}

function contentToDraft(content: PresetContent): Draft {
  const match = (m: PresetMatchConditions): MatchDraft => ({
    pathGlob: m.pathGlob ?? '',
    extensions: (m.extensions ?? []).join(', '),
    categories: (m.categories ?? []).join(', '),
    sourceLabel: m.sourceLabel ?? '',
  });
  return {
    description: content.description ?? '',
    fallbackTemplate: content.fallbackTemplate,
    conflictPolicy: content.conflictPolicy,
    rules: content.rules.map((r) => ({ id: r.id, destination: r.destination, ...match(r.match) })),
    groups: content.groups.map((g) => ({
      id: g.id,
      destination: g.destination,
      ...match(g.match),
    })),
    exclusions: content.exclusions.map((e) => ({
      id: e.id,
      reason: e.reason,
      ...match(e.match),
    })),
  };
}

function blankDraft(): Draft {
  return {
    description: '',
    fallbackTemplate: ENGINE_DEFAULT_FALLBACK,
    conflictPolicy: 'keep_both',
    rules: [],
    groups: [],
    exclusions: [],
  };
}

export function Presets(): JSX.Element {
  const presets = useAsync(() => window.ferry.profile.list());
  const [presetId, setPresetId] = useState<number | null>(null);
  // null means "the latest revision".
  const [revision, setRevision] = useState<number | null>(null);
  const detail = useAsync<PresetRevisionDetail | null>(
    async () =>
      presetId === null ? null : window.ferry.profile.getRevision(presetId, revision ?? undefined),
    [presetId, revision],
  );
  const revisions = useAsync(
    async () =>
      presetId === null
        ? { revisions: [], total: 0 }
        : window.ferry.profile.listRevisions(presetId),
    [presetId],
  );

  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [preview, setPreview] = useState<readonly string[] | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [importPayload, setImportPayload] = useState('');

  if (presets.loading) {
    return <ScreenLoading message="Reading saved presets…" />;
  }
  if (presets.error !== null) {
    return <ScreenError message={presets.error} onRetry={presets.reload} />;
  }
  const list = presets.data?.profiles ?? [];
  const selected = list.find((p) => p.id === presetId) ?? null;

  const shownRevision = detail.data?.revision ?? null;

  const saveRevision = async (): Promise<void> => {
    if (draft === null || selected === null) return;
    if (draft.fallbackTemplate.trim() === '') {
      setError('A preset needs a fallback template.');
      return;
    }
    const content: PresetContent = {
      name: selected.name,
      description: draft.description.trim() === '' ? null : draft.description.trim(),
      rules: draft.rules.map((r) => ({
        id: r.id.trim() === '' ? `rule-${r.destination.trim()}` : r.id.trim(),
        destination: r.destination.trim(),
        match: parseMatch(r),
      })),
      groups: draft.groups.map((g) => ({
        id: g.id.trim() === '' ? `group-${g.destination.trim()}` : g.id.trim(),
        destination: g.destination.trim(),
        match: parseMatch(g),
      })),
      fallbackTemplate: draft.fallbackTemplate.trim(),
      conflictPolicy: draft.conflictPolicy,
      exclusions: draft.exclusions.map((e) => ({
        id: e.id.trim() === '' ? `excl-${e.reason.trim()}` : e.id.trim(),
        reason: e.reason.trim(),
        match: parseMatch(e),
      })),
      reviewRequired: [],
    };
    setSaving(true);
    setError(null);
    try {
      const summary = await window.ferry.profile.saveRevision({
        name: selected.name,
        content,
      });
      setSavedNote(`saved as revision ${summary.revision} · ${summary.contentHash.slice(0, 12)}`);
      setDraft(null);
      revisions.reload();
      detail.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async (): Promise<void> => {
    if (draft === null) return;
    setPreviewing(true);
    try {
      // The one preview RPC is profile.preview; it sees the fallback
      // template (which is how the sidecar stores presets' fallback). It
      // does not evaluate rules — the button says "fallback" so the panel
      // never claims more than it shows.
      const result = await window.ferry.profile.preview({
        template: { root: draft.fallbackTemplate.trim() },
        sourceRoot: '/sample-card',
        destRoot: '/destination',
        entries: SAMPLE_ENTRIES,
      });
      setPreview(result.entries.map((e) => `${e.sourcePath} -> ${e.destPath ?? '—'}`));
    } catch (err) {
      setPreview([`preview failed: ${err instanceof Error ? err.message : String(err)}`]);
    } finally {
      setPreviewing(false);
    }
  };

  const importPreset = async (): Promise<void> => {
    if (importPayload.trim() === '') return;
    setError(null);
    try {
      const summary = await window.ferry.profile.import({ payload: importPayload.trim() });
      setImportPayload('');
      presets.reload();
      setPresetId(summary.presetId);
      setRevision(null);
      setSavedNote(`imported as revision ${summary.revision}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="page">
      {error !== null && <Banner tone="danger">{error}</Banner>}
      {savedNote !== null && (
        <Banner tone="ok" label="Saved">
          {savedNote}
        </Banner>
      )}

      <Panel
        title="Presets"
        description="Immutable revisions; destinations pin the one they were saved with."
      >
        {list.length === 0 ? (
          <EmptyState
            message="No presets yet"
            hint="A transfer can run without one — the engine's default routes under Sources/<label>. Author a preset when you want rules."
          />
        ) : (
          <div className="row" role="list" aria-label="Saved presets">
            {list.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`btn btn--sm${p.id === presetId ? ' btn--primary' : ''}`}
                aria-pressed={p.id === presetId}
                onClick={() => {
                  setPresetId(p.id);
                  setRevision(null);
                  setDraft(null);
                  setSavedNote(null);
                }}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}
      </Panel>

      {selected !== null && (
        <>
          <Panel title={`Revisions of ${selected.name}`} flush>
            {revisions.loading ? (
              <div className="card__body">
                <LoadingState message="Reading revisions…" />
              </div>
            ) : (revisions.data?.revisions ?? []).length === 0 ? (
              <div className="card__body">
                <p className="muted">No revisions recorded for this preset.</p>
              </div>
            ) : (
              <div className="table-wrap table-wrap--short">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Revision</th>
                      <th>Hash</th>
                      <th>Created</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(revisions.data?.revisions ?? []).map((r) => (
                      <tr key={r.revision}>
                        <td>
                          r{r.revision}{' '}
                          {r.revision === shownRevision ? <Chip tone="active">shown</Chip> : null}
                        </td>
                        <td className="mono">{r.contentHash.slice(0, 12)}</td>
                        <td>{r.createdAt}</td>
                        <td className="cell-actions">
                          <button
                            type="button"
                            className="btn btn--sm"
                            onClick={() => setRevision(r.revision)}
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          {detail.error !== null && <Banner tone="danger">{detail.error}</Banner>}
          {detail.data !== null && <RevisionDetail revision={detail.data} />}

          <Panel
            title="New revision"
            description="Saving appends; nothing in place changes. Seed from the shown revision or start from the engine default."
            actions={
              <>
                <button
                  type="button"
                  className="btn"
                  disabled={detail.data === null}
                  onClick={() => {
                    if (detail.data !== null) {
                      setDraft(contentToDraft(detail.data.content));
                      setSavedNote(null);
                    }
                  }}
                >
                  Seed from shown
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setDraft(blankDraft());
                    setSavedNote(null);
                  }}
                >
                  Start blank
                </button>
              </>
            }
          >
            {draft === null ? (
              <p className="muted">Nothing being edited right now.</p>
            ) : (
              <PresetEditor
                draft={draft}
                onChange={setDraft}
                onSave={saveRevision}
                saving={saving}
                onPreview={runPreview}
                previewing={previewing}
                preview={preview}
              />
            )}
          </Panel>
        </>
      )}

      <Panel
        title="Import / export"
        description="A payload is a portable revision; importing appends it as a new revision."
      >
        <div className="stack">
          <Field label="Paste an exported payload to import">
            <textarea
              id="preset-import"
              rows={4}
              value={importPayload}
              onChange={(e) => setImportPayload(e.target.value)}
              placeholder="Paste an exported revision here"
            />
          </Field>
          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={importPayload.trim() === ''}
              onClick={importPreset}
            >
              Import
            </button>
            <ExportRow presetId={presetId} />
          </div>
        </div>
      </Panel>
    </div>
  );
}

function RevisionDetail({ revision }: { revision: PresetRevisionDetail }): JSX.Element {
  const c = revision.content;
  const reviewRequired = c.reviewRequired ?? [];
  return (
    <Panel
      title={`r${revision.revision} content`}
      description={`${revision.createdAt} · ${revision.contentHash.slice(0, 12)}`}
    >
      <div className="stack">
        {revision.legacySnapshot && (
          <Banner tone="attention" label="Legacy snapshot">
            Converted from a legacy profile template and kept verbatim, so the conversion can be
            audited against its input.
          </Banner>
        )}
        {reviewRequired.length > 0 && (
          <Banner tone="attention" label="Needs a decision">
            {`This revision still needs a decision about: ${reviewRequired.join(', ')}. Plan approval is refused until it is resolved.`}
          </Banner>
        )}
        <p>
          <span className="eyebrow">Fallback</span> <code>{c.fallbackTemplate}</code>
        </p>
        <p>
          <span className="eyebrow">Conflict default</span> <code>{c.conflictPolicy}</code>
        </p>
        {c.rules.length > 0 && (
          <div>
            <p className="eyebrow">Ordered rules — first match wins</p>
            <ol className="stack">
              {c.rules.map((r) => (
                <li key={r.id}>
                  <code>{r.destination}</code> <MatchText match={r.match} />
                </li>
              ))}
            </ol>
          </div>
        )}
        {c.groups.length > 0 && (
          <div>
            <p className="eyebrow">Keep-together groups</p>
            <ul className="stack">
              {c.groups.map((g) => (
                <li key={g.id}>
                  <code>{g.destination}</code> <MatchText match={g.match} />
                </li>
              ))}
            </ul>
          </div>
        )}
        {c.exclusions.length > 0 && (
          <div>
            <p className="eyebrow">Exclusions</p>
            <ul className="stack">
              {c.exclusions.map((e) => (
                <li key={e.id}>
                  {e.reason} <MatchText match={e.match} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}

function MatchText({ match }: { match: PresetMatchConditions }): JSX.Element {
  const parts: string[] = [];
  if (match.pathGlob !== null && match.pathGlob !== undefined)
    parts.push(`path ~ ${match.pathGlob}`);
  if (match.extensions !== null && match.extensions !== undefined && match.extensions.length > 0)
    parts.push(`ext ${match.extensions.join(', ')}`);
  if (match.categories !== null && match.categories !== undefined && match.categories.length > 0)
    parts.push(`cat ${match.categories.join(', ')}`);
  if (match.sourceLabel) parts.push(`source ${match.sourceLabel}`);
  return (
    <span className="muted">{parts.length === 0 ? '(matches everything)' : parts.join(' · ')}</span>
  );
}

function ExportRow({ presetId }: { presetId: number | null }): JSX.Element {
  const [payload, setPayload] = useState<string | null>(null);
  if (presetId === null) {
    return <span className="muted">Select a preset to export its latest revision.</span>;
  }
  return (
    <span className="row">
      <button
        type="button"
        className="btn btn--sm"
        onClick={async () => setPayload((await window.ferry.profile.export(presetId)).payload)}
      >
        Export latest
      </button>
      {payload !== null && (
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => {
            void navigator.clipboard?.writeText(payload);
          }}
        >
          Copy payload
        </button>
      )}
    </span>
  );
}

function PresetEditor({
  draft,
  onChange,
  onSave,
  saving,
  onPreview,
  previewing,
  preview,
}: {
  draft: Draft;
  onChange: (d: Draft) => void;
  onSave: () => void;
  saving: boolean;
  onPreview: () => void;
  previewing: boolean;
  preview: readonly string[] | null;
}): JSX.Element {
  const set = <K extends keyof Draft>(key: K, value: Draft[K]): void =>
    onChange({ ...draft, [key]: value });

  const reorder = (
    list: readonly RouteDraft[],
    index: number,
    delta: number,
  ): readonly RouteDraft[] => {
    const next = [...list];
    const target = index + delta;
    if (target < 0 || target >= next.length) return list;
    [next[index], next[target]] = [next[target]!, next[index]!];
    return next;
  };

  return (
    <div className="stack">
      <div className="field-grid">
        <Field
          label="Fallback template"
          hint="Where a file lands when no rule and no group matched it."
        >
          <input
            id="preset-fallback"
            value={draft.fallbackTemplate}
            onChange={(e) => set('fallbackTemplate', e.target.value)}
          />
        </Field>
        <Field label="Conflict default">
          <select
            id="preset-conflict"
            value={draft.conflictPolicy}
            // SAFETY: the <option> list renders exactly the three
            // conflict policies PresetContent accepts.
            onChange={(e) =>
              set('conflictPolicy', e.target.value as PresetContent['conflictPolicy'])
            }
          >
            {CONFLICT_POLICIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Description">
          <input
            id="preset-description"
            value={draft.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </Field>
      </div>

      <Panel
        title={`Ordered rules (${draft.rules.length})`}
        description="First match wins; the list order is the priority. An empty field does not constrain."
        flush
      >
        <div className="card__body stack">
          {draft.rules.length === 0 ? (
            <p className="muted">No rules — everything falls through to the fallback template.</p>
          ) : (
            draft.rules.map((r, i) => (
              <RouteRow
                key={i}
                heading={`Rule ${i + 1}`}
                row={r}
                count={draft.rules.length}
                onChange={(next) => {
                  const rules = [...draft.rules];
                  rules[i] = next;
                  set('rules', rules);
                }}
                onRemove={() =>
                  set(
                    'rules',
                    draft.rules.filter((_, j) => j !== i),
                  )
                }
                onMove={(delta) => set('rules', reorder(draft.rules, i, delta))}
              />
            ))
          )}
          <button
            type="button"
            className="btn btn--sm"
            onClick={() =>
              set('rules', [
                ...draft.rules,
                { id: `rule-${draft.rules.length + 1}`, destination: '', ...EMPTY_MATCH },
              ])
            }
          >
            Add rule
          </button>
        </div>
      </Panel>

      <Panel
        title={`Keep-together groups (${draft.groups.length})`}
        description="A group routes as one unit: the destination is decided once at its root, members append unchanged."
        flush
      >
        <div className="card__body stack">
          {draft.groups.length === 0 ? (
            <p className="muted">No groups.</p>
          ) : (
            draft.groups.map((g, i) => (
              <RouteRow
                key={i}
                heading={`Group ${i + 1}`}
                row={g}
                count={draft.groups.length}
                onChange={(next) => {
                  const groups = [...draft.groups];
                  groups[i] = next;
                  set('groups', groups);
                }}
                onRemove={() =>
                  set(
                    'groups',
                    draft.groups.filter((_, j) => j !== i),
                  )
                }
              />
            ))
          )}
          <button
            type="button"
            className="btn btn--sm"
            onClick={() =>
              set('groups', [
                ...draft.groups,
                { id: `group-${draft.groups.length + 1}`, destination: '', ...EMPTY_MATCH },
              ])
            }
          >
            Add group
          </button>
        </div>
      </Panel>

      <Panel
        title={`Exclusions (${draft.exclusions.length})`}
        description="Applied before routing; the reason is recorded in the receipt for every file left behind."
        flush
      >
        <div className="card__body stack">
          {draft.exclusions.length === 0 ? (
            <p className="muted">No exclusions.</p>
          ) : (
            draft.exclusions.map((e, i) => (
              <ExclusionRow
                key={i}
                heading={`Exclusion ${i + 1}`}
                row={e}
                onChange={(next) => {
                  const exclusions = [...draft.exclusions];
                  exclusions[i] = next;
                  set('exclusions', exclusions);
                }}
                onRemove={() =>
                  set(
                    'exclusions',
                    draft.exclusions.filter((_, j) => j !== i),
                  )
                }
              />
            ))
          )}
          <button
            type="button"
            className="btn btn--sm"
            onClick={() =>
              set('exclusions', [
                ...draft.exclusions,
                { id: `excl-${draft.exclusions.length + 1}`, reason: '', ...EMPTY_MATCH },
              ])
            }
          >
            Add exclusion
          </button>
        </div>
      </Panel>

      <div className="stack">
        <div className="row">
          <button type="button" className="btn" onClick={onPreview} disabled={previewing}>
            {previewing ? 'Previewing…' : 'Sample preview (fallback)'}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={saving || draft.fallbackTemplate.trim() === ''}
            onClick={onSave}
          >
            {saving ? 'Saving…' : 'Save revision'}
          </button>
        </div>
        {preview !== null && (
          <table className="table">
            <thead>
              <tr>
                <th>Sample preview</th>
              </tr>
            </thead>
            <tbody>
              {preview.map((line) => (
                <tr key={line}>
                  <td className="mono">{line}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function RouteRow({
  heading,
  row,
  count,
  onChange,
  onRemove,
  onMove,
  index,
}: {
  heading: string;
  row: RouteDraft;
  count: number;
  onChange: (next: RouteDraft) => void;
  onRemove?: (() => void) | undefined;
  onMove?: ((delta: number) => void) | undefined;
  index?: number | undefined;
}): JSX.Element {
  return (
    <fieldset className="field">
      <label>{heading}</label>
      <div className="field-grid">
        <Field label="Id">
          <input value={row.id} onChange={(e) => onChange({ ...row, id: e.target.value })} />
        </Field>
        <Field label="Destination template">
          <input
            value={row.destination}
            onChange={(e) => onChange({ ...row, destination: e.target.value })}
          />
        </Field>
      </div>
      <MatchInputs match={row} onChange={(m) => onChange({ ...row, ...m })} />
      <div className="row">
        {onMove !== undefined && index !== undefined && (
          <>
            <button
              type="button"
              className="btn btn--sm"
              disabled={index === 0}
              onClick={() => onMove(-1)}
            >
              ↑ Higher priority
            </button>
            <button
              type="button"
              className="btn btn--sm"
              disabled={index === count - 1}
              onClick={() => onMove(1)}
            >
              ↓ Lower priority
            </button>
          </>
        )}
        {onRemove !== undefined && (
          <button type="button" className="btn btn--sm btn--danger" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>
    </fieldset>
  );
}

function ExclusionRow({
  heading,
  row,
  onChange,
  onRemove,
}: {
  heading: string;
  row: ExclusionDraft;
  onChange: (next: ExclusionDraft) => void;
  onRemove: () => void;
}): JSX.Element {
  return (
    <fieldset className="field">
      <label>{heading}</label>
      <Field label="Reason — recorded in the receipt for every file it leaves behind">
        <input value={row.reason} onChange={(e) => onChange({ ...row, reason: e.target.value })} />
      </Field>
      <MatchInputs match={row} onChange={(m) => onChange({ ...row, ...m })} />
      <div className="row">
        <button type="button" className="btn btn--sm btn--danger" onClick={onRemove}>
          Remove
        </button>
      </div>
    </fieldset>
  );
}

function MatchInputs({
  match,
  onChange,
}: {
  match: MatchDraft;
  onChange: (m: MatchDraft) => void;
}): JSX.Element {
  return (
    <div className="field-grid">
      <Field label="Path glob">
        <input
          value={match.pathGlob}
          onChange={(e) => onChange({ ...match, pathGlob: e.target.value })}
        />
      </Field>
      <Field label="Extensions (comma-separated)">
        <input
          value={match.extensions}
          onChange={(e) => onChange({ ...match, extensions: e.target.value })}
        />
      </Field>
      <Field label="Categories (comma-separated)">
        <input
          value={match.categories}
          onChange={(e) => onChange({ ...match, categories: e.target.value })}
        />
      </Field>
      <Field label="Source label">
        <input
          value={match.sourceLabel}
          onChange={(e) => onChange({ ...match, sourceLabel: e.target.value })}
        />
      </Field>
    </div>
  );
}
