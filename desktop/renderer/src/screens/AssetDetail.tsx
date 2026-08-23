/**
 * Media screen.
 *
 * Two routes share one screen: `#/asset` lists the library (optionally
 * filtered to one project via `?project=`), and `#/asset?id=…` is the
 * detail for a single asset — metadata, source provenance, every replica,
 * verification/proxy state, and clip grouping (plan §8.2).
 *
 * The selection lives in the hash rather than in component state so it
 * survives a reload and so Projects can link straight to a project's media.
 */
import { useAsync } from '../hooks/useAsync.js';
import { useRoute } from '../hooks/useRoute.js';
import {
  Chip,
  EmptyState,
  ErrorState,
  KeyValue,
  LoadingState,
  Panel,
  PathCell,
  Progress,
  type Tone,
} from '../components/ui.js';
import {
  assetFileName,
  assetOverview,
  proxyReadiness,
  replicaHealth,
  searchAssets,
  sortAssets,
} from '../lib/asset.js';
import { navigateTo } from '../views.js';
import { useState } from 'react';
import type { ReplicaSummary } from '../../../shared/ipc-methods.js';
import type { AssetOverview } from '../lib/asset.js';

export function AssetDetail(): JSX.Element {
  const route = useRoute('asset');
  const assetId = route.params.get('id') ?? null;
  const projectId = route.params.get('project') ?? null;

  // Split rather than branching inside one component: each half owns a
  // different set of requests, and a conditional early return above hooks
  // would be a rules-of-hooks violation.
  return assetId === null ? (
    <AssetBrowser projectId={projectId} />
  ) : (
    <AssetView assetId={assetId} projectId={projectId} />
  );
}

function AssetBrowser({ projectId }: { projectId: string | null }): JSX.Element {
  // Spread into each destination so the project the operator arrived with
  // survives the trip into a detail view and back.
  const filter = projectId === null ? {} : { project: projectId };
  const projects = useAsync(() => window.ferry.project.list());
  const assets = useAsync(
    () => window.ferry.asset.list(projectId === null ? {} : { projectId }),
    [projectId],
  );
  const [query, setQuery] = useState('');

  if (assets.loading) {
    return <LoadingState message="Loading media…" />;
  }
  if (assets.error !== null) {
    return <ErrorState message={assets.error} />;
  }

  const all = assets.data?.assets ?? [];
  const rows = sortAssets(searchAssets(all, query));
  const projectList = projects.data?.projects ?? [];
  const activeProject = projectList.find((p) => p.id === projectId) ?? null;

  return (
    <div className="page">
      <Panel
        title="Media"
        description={
          activeProject === null
            ? `${all.length} asset${all.length === 1 ? '' : 's'} across all projects`
            : `${all.length} asset${all.length === 1 ? '' : 's'} in ${activeProject.name}`
        }
        actions={
          <>
            <select
              className="toolbar__select"
              aria-label="Filter media by project"
              value={projectId ?? ''}
              onChange={(e) =>
                navigateTo('asset', e.target.value === '' ? {} : { project: e.target.value })
              }
            >
              <option value="">All projects</option>
              {projectList.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <input
              type="search"
              className="toolbar__search"
              aria-label="Search media"
              placeholder="Search path, kind, state…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </>
        }
        flush={rows.length > 0}
      >
        {rows.length === 0 ? (
          <EmptyState
            message={all.length === 0 ? 'No media yet' : 'No media matches'}
            hint={
              all.length === 0
                ? 'Assets appear here once an offload or an organize run has adopted them.'
                : 'Try a different search, or widen the project filter.'
            }
            action={
              all.length === 0 ? (
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => navigateTo('ingest')}
                >
                  Go to Offload
                </button>
              ) : (
                <button type="button" className="btn" onClick={() => setQuery('')}>
                  Clear search
                </button>
              )
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Path</th>
                  <th>Kind</th>
                  <th className="cell-num">Size</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((asset) => (
                  <tr key={asset.id}>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => navigateTo('asset', { ...filter, id: asset.id })}
                      >
                        {assetFileName(asset.sourceRelativePath)}
                      </button>
                    </td>
                    <td>
                      <PathCell path={asset.sourceRelativePath} />
                    </td>
                    <td className="muted">{asset.mediaKind ?? '—'}</td>
                    <td className="cell-num muted">
                      {asset.observedSize === null ? '—' : formatBytes(asset.observedSize)}
                    </td>
                    <td>
                      <Chip>{asset.lifecycleState}</Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function AssetView({
  assetId,
  projectId,
}: {
  assetId: string;
  projectId: string | null;
}): JSX.Element {
  const asset = useAsync(() => window.ferry.asset.get(assetId), [assetId]);
  const replicas = useAsync(() => window.ferry.replica.list(assetId), [assetId]);
  const derivatives = useAsync(() => window.ferry.derivatives.list(assetId), [assetId]);
  const clips = useAsync(() => window.ferry.clips.list(Number(assetId)), [assetId]);

  const filter = projectId === null ? {} : { project: projectId };
  const back = (
    <button type="button" className="btn btn--sm" onClick={() => navigateTo('asset', filter)}>
      ← All media
    </button>
  );

  if (asset.loading) {
    return <LoadingState message="Loading asset…" />;
  }
  if (asset.error !== null) {
    return (
      <div className="page">
        <div className="page__intro">
          <div className="grow" />
          <div className="page__intro-actions">{back}</div>
        </div>
        <ErrorState message={asset.error} />
      </div>
    );
  }
  const a = asset.data;
  if (a === null) {
    return (
      <div className="page">
        <Panel actions={back}>
          <EmptyState
            message="Asset not found"
            hint="It may have been removed since this link was made."
          />
        </Panel>
      </div>
    );
  }

  const overview = assetOverview({
    replicas: replicas.data?.replicas ?? [],
    derivatives: derivatives.data ?? [],
    clips: clips.data ?? [],
  });
  const readiness = proxyReadiness(overview);

  return (
    <div className="page">
      <div className="page__intro">
        <div className="grow">
          <div className="page__title">{assetFileName(a.sourceRelativePath)}</div>
          <PathCell path={a.sourceRelativePath} />
        </div>
        <div className="page__intro-actions">
          <Chip>{a.lifecycleState}</Chip>
          {back}
        </div>
      </div>

      <Panel title="Metadata">
        <KeyValue
          rows={[
            { label: 'Media kind', value: a.mediaKind ?? <span className="faint">unknown</span> },
            {
              label: 'Size',
              value:
                a.observedSize === null ? (
                  <span className="faint">—</span>
                ) : (
                  formatBytes(a.observedSize)
                ),
            },
            {
              label: 'Source id',
              value: a.sourceId === null ? <span className="faint">—</span> : String(a.sourceId),
            },
            { label: 'First seen', value: a.firstSeenAt },
          ]}
        />
      </Panel>

      <Panel
        title="Replicas"
        description="Every copy ferry knows about, and whether it has been verified"
        flush={overview.replicas.length > 0}
      >
        <ReplicaTable overview={overview} />
      </Panel>

      <Panel
        title="Proxy state"
        description="Derivatives generated for editing"
        actions={<Chip tone={proxyTone(readiness)}>{readiness}</Chip>}
        flush={overview.derivatives.length > 0}
      >
        {overview.derivatives.length === 0 ? (
          <EmptyState
            message="No derivatives"
            hint="Proxies are generated after an offload verifies."
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Readiness</th>
                </tr>
              </thead>
              <tbody>
                {overview.derivatives.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <code>{d.kind}</code>
                    </td>
                    <td className="muted">{d.status}</td>
                    <td>
                      <Progress
                        percent={Math.round(d.readiness * 100)}
                        label={`${d.kind} readiness`}
                        tone={d.status === 'ready' ? 'ok' : 'neutral'}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Logical clips"
        description="Spanned or multi-file recordings this asset belongs to"
      >
        {overview.clips.length === 0 ? (
          <EmptyState message="Not part of any clip group" />
        ) : (
          <ul className="plain-list">
            {overview.clips.map((c) => (
              <li key={c.id}>
                <span className="grow">{c.clipName}</span>
                <Chip tone={c.resolved ? 'ok' : 'warn'}>{c.resolved ? 'resolved' : 'partial'}</Chip>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function ReplicaTable({ overview }: { overview: AssetOverview }): JSX.Element {
  if (overview.replicas.length === 0) {
    return (
      <EmptyState
        message="No replicas recorded"
        hint="A verified copy is written by an offload job."
      />
    );
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Path</th>
            <th>Status</th>
            <th>Checksum</th>
          </tr>
        </thead>
        <tbody>
          {overview.replicas.map((r: ReplicaSummary) => (
            <tr key={r.id}>
              <td>
                <PathCell path={r.path} />
              </td>
              <td>
                <Chip tone={replicaTone(replicaHealth(r))}>{replicaHealth(r)}</Chip>
              </td>
              <td className="muted">
                {r.verified ? 'verified' : <span className="faint">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function replicaTone(h: ReturnType<typeof replicaHealth>): Tone {
  if (h === 'verified') return 'ok';
  if (h === 'missing') return 'danger';
  return 'warn';
}

function proxyTone(r: ReturnType<typeof proxyReadiness>): Tone {
  if (r === 'ready') return 'ok';
  return r === 'pending' ? 'warn' : 'neutral';
}

function formatBytes(n: number): string {
  if (n >= 1e12) return `${(n / 1e12).toFixed(1)} TB`;
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${n} B`;
}
