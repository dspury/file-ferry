/**
 * Asset / Clip detail screen.
 *
 * Metadata, source provenance, logical grouping, every replica,
 * verification/proxy state, and related clips (plan §8.2). Uses the first
 * asset as a safe default until a project-detail selection passes one in.
 */
import { useAsync } from '../hooks/useAsync.js';
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
import { assetOverview, replicaHealth, proxyReadiness } from '../lib/asset.js';
import { navigateTo } from '../views.js';
import type { ReplicaSummary } from '../../../shared/ipc-methods.js';
import type { AssetOverview } from '../lib/asset.js';

export function AssetDetail(): JSX.Element {
  // TODO(7c): replace the default with real navigation from Projects. The
  // first asset is shown as a safe default so the screen is navigable.
  const assets = useAsync(() => window.ferry.asset.list());
  const assetId = assets.data?.assets[0]?.id;

  const asset = useAsync(() => window.ferry.asset.get(assetId ?? ''), [assetId]);
  const replicas = useAsync(() => window.ferry.replica.list(assetId ?? ''), [assetId]);
  const derivatives = useAsync(() => window.ferry.derivatives.list(assetId ?? ''), [assetId]);
  const clips = useAsync(() => window.ferry.clips.list(assetId ? Number(assetId) : 0), [assetId]);

  if (assets.loading) {
    return <LoadingState message="Loading media…" />;
  }
  // An empty library is not an error — it is the normal state before the
  // first offload, and it should say what to do about it.
  if (assetId === undefined) {
    return (
      <div className="page">
        <Panel>
          <EmptyState
            message="No media yet"
            hint="Assets appear here once an offload or an organize run has adopted them."
            action={
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => navigateTo('ingest')}
              >
                Go to Offload
              </button>
            }
          />
        </Panel>
      </div>
    );
  }
  if (asset.error !== null) {
    return <ErrorState message={asset.error} />;
  }
  const a = asset.data;
  if (a === null) {
    return <ErrorState message="No asset data." />;
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
          <PathCell path={a.sourceRelativePath} />
        </div>
        <Chip>{a.lifecycleState}</Chip>
      </div>

      <Panel title="Metadata">
        <KeyValue
          rows={[
            { label: 'Media kind', value: a.mediaKind ?? <span className="faint">unknown</span> },
            {
              label: 'Size',
              value:
                a.observedSize != null ? (
                  formatBytes(a.observedSize)
                ) : (
                  <span className="faint">—</span>
                ),
            },
            { label: 'Source id', value: a.sourceId ?? <span className="faint">—</span> },
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
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${n} B`;
}
