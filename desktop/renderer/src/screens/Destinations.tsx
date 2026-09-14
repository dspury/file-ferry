/**
 * Destinations screen.
 *
 * The saved destination is a durable record; whether it can be used right
 * now is a live question the resolver answers by looking at what is
 * mounted. This screen keeps the two visibly separate: the table shows the
 * saved record, and each row's availability is `destination.resolve`'s
 * answer with its reason — never colour alone.
 *
 * Archiving invalidates the destination's unexecuted plans in the same
 * sidecar transaction, so it goes through the confirm dialog: the thing
 * being destroyed (the plans, not the data) is what the phrase names.
 */
import { useState } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import {
  Banner,
  Chip,
  EmptyState,
  Field,
  Panel,
  PathPicker,
  ScreenError,
  ScreenLoading,
  StatCard,
} from '../components/ui.js';
import { ConfirmDialog } from '../components/ConfirmDialog.js';
import { destinationStatusTone } from '../lib/transfers.js';
import type {
  DestinationResolution,
  DestinationSummary,
  OrganizationProfile,
} from '../../../shared/ipc-methods.js';
import type { JSX as JSXType } from 'react';

const CONFLICT_POLICIES = ['keep_both', 'skip_identical', 'needs_review'] as const;
const CHECKSUM_ALGOS = ['xxhash64', 'sha256'] as const;

interface DestinationsData {
  readonly destinations: readonly DestinationSummary[];
  readonly resolutions: readonly DestinationResolution[];
  readonly presets: readonly OrganizationProfile[];
  readonly volumes: number;
  readonly discoveryStale: boolean;
  readonly discoveryWarnings: readonly string[];
}

export function Destinations(): JSXType.Element {
  const loaded = useAsync<DestinationsData>(async () => {
    const [list, resolve, profiles, discovery] = await Promise.all([
      window.ferry.destination.list(),
      window.ferry.destination.resolve(),
      window.ferry.profile.list(),
      window.ferry.destination.discovery(),
    ]);
    return {
      destinations: list.destinations,
      resolutions: resolve.resolutions,
      presets: profiles.profiles,
      volumes: discovery.volumes.length,
      discoveryStale: discovery.stale,
      discoveryWarnings: discovery.warnings,
    };
  });

  const [showForm, setShowForm] = useState(false);
  // SAFETY: the two `as` casts below pin the form's values to the exact
  // literal unions the <select> options render and destination.save accepts;
  // the invariant is maintained at every setForm call site.
  const [form, setForm] = useState({
    name: '',
    path: null as string | null,
    subfolder: '',
    presetId: '' as '' | number,
    conflictPolicy: 'keep_both' as (typeof CONFLICT_POLICIES)[number],
    checksumAlgo: 'xxhash64' as (typeof CHECKSUM_ALGOS)[number],
    freeSpaceReserve: 0,
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedName, setSavedName] = useState<string | null>(null);
  const [archiving, setArchiving] = useState<DestinationSummary | null>(null);

  if (loaded.loading) {
    return <ScreenLoading message="Reading saved destinations…" />;
  }
  if (loaded.error !== null) {
    return <ScreenError message={loaded.error} onRetry={loaded.reload} />;
  }
  if (loaded.data === null) {
    return <ScreenError message="The sidecar returned no destinations." onRetry={loaded.reload} />;
  }
  const data = loaded.data;

  const availabilityOf = (id: number): DestinationResolution | undefined =>
    data.resolutions.find((r) => r.destinationId === id);

  const pickPath = async () => {
    const result = await window.ferry.dialog.pick({ kind: 'directory' });
    if (!result.cancelled && result.path) setForm((f) => ({ ...f, path: result.path }));
  };

  const save = async () => {
    if (form.name.trim() === '' || form.path === null) {
      setSaveError('A destination needs a name and a path.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await window.ferry.destination.save({
        name: form.name,
        path: form.path,
        subfolderPath: form.subfolder === '' ? null : form.subfolder,
        defaultPresetId: form.presetId === '' ? null : form.presetId,
        conflictPolicy: form.conflictPolicy,
        checksumAlgo: form.checksumAlgo,
        freeSpaceReserve: form.freeSpaceReserve,
      });
      setSavedName(form.name);
      setShowForm(false);
      setForm({
        name: '',
        path: null,
        subfolder: '',
        presetId: '',
        conflictPolicy: 'keep_both',
        checksumAlgo: 'xxhash64',
        freeSpaceReserve: 0,
      });
      loaded.reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    if (archiving === null) return;
    try {
      await window.ferry.destination.archive(archiving.id);
      setArchiving(null);
      loaded.reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
      setArchiving(null);
    }
  };

  return (
    <div className="page">
      <div className="stats">
        <StatCard label="Saved destinations" value={data.destinations.length} />
        <StatCard
          label="Available now"
          value={data.resolutions.filter((r) => r.status === 'available').length}
          tone="ok"
        />
        <StatCard
          label="Needs a decision"
          value={
            data.resolutions.filter(
              (r) => r.status === 'needs_confirmation' || r.status === 'ambiguous',
            ).length
          }
          tone={data.resolutions.some((r) => r.status === 'ambiguous') ? 'attention' : 'neutral'}
        />
      </div>

      {data.discoveryStale || data.discoveryWarnings.length > 0 ? (
        <Banner tone="attention" label="Storage discovery">
          {data.discoveryWarnings.length > 0
            ? data.discoveryWarnings.join(' ')
            : 'The last observation is stale; resolve before trusting availability.'}
        </Banner>
      ) : null}

      {savedName !== null && (
        <Banner tone="ok" label="Saved">
          {`Destination “${savedName}” saved. Its preset revision is pinned at save time; a newer revision never re-routes it on its own.`}
        </Banner>
      )}

      <Panel
        title="Saved destinations"
        description="A saved record of where media goes. Live availability is shown per row."
        actions={
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              setShowForm((v) => !v);
              setSavedName(null);
            }}
          >
            {showForm ? 'Close form' : 'Save destination'}
          </button>
        }
        flush
      >
        {data.destinations.length === 0 ? (
          <div className="card__body">
            <EmptyState
              message="No saved destinations"
              hint="Save the folder a card should land in, and pin the preset that routes it."
              // Duplicated "Save destination" read as two independent
              // controls; the header button is the real control.
              action={
                <button type="button" className="btn" onClick={() => setShowForm(true)}>
                  Save the first one
                </button>
              }
            />
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Root</th>
                  <th>Preset</th>
                  <th>Availability</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.destinations.map((d) => {
                  const resolution = availabilityOf(d.id);
                  const preset = data.presets.find((p) => p.id === d.defaultPresetId);
                  return (
                    <tr key={d.id}>
                      <td>{d.name}</td>
                      <td>
                        <span className="cell-path">{d.lastRootPath}</span>
                      </td>
                      <td>
                        {d.defaultPresetId === null
                          ? '—'
                          : `${preset?.name ?? `preset ${d.defaultPresetId}`} @ r${d.pinnedRevision ?? '?'}`}
                      </td>
                      <td>
                        {resolution === undefined ? (
                          '—'
                        ) : (
                          <span className="row">
                            <Chip tone={destinationStatusTone(resolution.status)}>
                              {resolution.status}
                            </Chip>
                            <span className="muted">{resolution.reason}</span>
                          </span>
                        )}
                      </td>
                      <td className="cell-actions">
                        <div className="row">
                          <button
                            type="button"
                            className="btn btn--sm"
                            onClick={() => loaded.reload()}
                          >
                            Re-resolve
                          </button>
                          <button
                            type="button"
                            className="btn btn--sm btn--danger"
                            onClick={() => setArchiving(d)}
                          >
                            Archive
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {showForm && (
        <Panel title="Save a destination" description="Pins the chosen preset's current revision.">
          <div className="field-grid">
            <Field label="Name">
              <input
                id="dest-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Editing NAS"
              />
            </Field>
            <Field label="Root path">
              <PathPicker value={form.path} onPick={pickPath} buttonLabel="Browse…" />
            </Field>
            <Field label="Subfolder" hint="Optional path under the root.">
              <input
                id="dest-subfolder"
                value={form.subfolder}
                onChange={(e) => setForm((f) => ({ ...f, subfolder: e.target.value }))}
                placeholder="{project}"
              />
            </Field>
            <Field label="Preset (pins its current revision)">
              <select
                id="dest-preset"
                value={form.presetId}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    presetId: e.target.value === '' ? '' : Number(e.target.value),
                  }))
                }
              >
                <option value="">No preset</option>
                {data.presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Conflict policy">
              <select
                id="dest-conflict"
                value={form.conflictPolicy}
                onChange={(e) =>
                  // SAFETY: the <option> list renders exactly
                  // CONFLICT_POLICIES, so the change event's value is one
                  // of them by construction.
                  setForm((f) => ({
                    ...f,
                    conflictPolicy: e.target.value as (typeof CONFLICT_POLICIES)[number],
                  }))
                }
              >
                {CONFLICT_POLICIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Checksum algorithm">
              <select
                id="dest-checksum"
                value={form.checksumAlgo}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    // SAFETY: the <option> list renders exactly
                    // CHECKSUM_ALGOS, so the value is one of them.
                    checksumAlgo: e.target.value as (typeof CHECKSUM_ALGOS)[number],
                  }))
                }
              >
                {CHECKSUM_ALGOS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Free-space reserve (bytes)"
              hint="Kept unclaimed on the destination before a transfer is allowed."
            >
              <input
                id="dest-reserve"
                type="number"
                min={0}
                value={form.freeSpaceReserve}
                onChange={(e) =>
                  setForm((f) => ({ ...f, freeSpaceReserve: Number(e.target.value) || 0 }))
                }
              />
            </Field>
          </div>
          {saveError !== null && <Banner tone="danger">{saveError}</Banner>}
          <div className="form-actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={saving || form.name.trim() === '' || form.path === null}
              onClick={save}
            >
              {saving ? 'Saving…' : 'Save destination'}
            </button>
            <span className="muted">
              {form.path === null
                ? 'Choose a folder first.'
                : `${data.volumes} volume(s) observed; availability is resolved after saving.`}
            </span>
          </div>
        </Panel>
      )}

      {saveError !== null && !showForm && <Banner tone="danger">{saveError}</Banner>}

      {archiving !== null && (
        <ConfirmDialog
          title={`Archive ${archiving.name}?`}
          body={`Archiving ${archiving.name} invalidates its unexecuted plans in the same operation — an approval that briefly outlived this configuration must not authorize a transfer. Historical executed plans are never touched.`}
          phrase={`ARCHIVE ${archiving.name}`}
          confirmLabel="Archive"
          onConfirm={archive}
          onCancel={() => setArchiving(null)}
        />
      )}
    </div>
  );
}
