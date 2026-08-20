/**
 * Asset / Clip detail screen.
 *
 * Metadata, source provenance, logical grouping, every replica,
 * verification/proxy state, and related clips (plan §8.2). Uses a simple
 * prompt for the asset id until a project-detail selection passes one in.
 */
import { useAsync } from '../hooks/useAsync.js';
import { Chip, Panel, LoadingState, ErrorState, type Tone } from '../components/ui.js';
import { assetOverview, replicaHealth, proxyReadiness } from '../lib/asset.js';

export function AssetDetail(): JSX.Element {
  // TODO(7c): replace the prompt with real navigation from Projects. The
  // first asset is shown as a safe default so the screen is navigable.
  const assets = useAsync(() => window.ferry.asset.list());
  const assetId = assets.data?.assets[0]?.id;

  const asset = useAsync(() => window.ferry.asset.get(assetId ?? ''), [assetId]);
  const replicas = useAsync(() => window.ferry.replica.list(assetId ?? ''), [assetId]);
  const derivatives = useAsync(() => window.ferry.derivatives.list(assetId ?? ''), [assetId]);
  const clips = useAsync(() => window.ferry.clips.list(assetId ? Number(assetId) : 0), [assetId]);

  if (assets.loading || !assetId) {
    return <LoadingState message="Loading assets…" />;
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

  return (
    <div className="stack">
      <h2>Asset detail</h2>
      <p className="muted">
        {a.sourceRelativePath} · <Chip>{a.lifecycleState}</Chip>
      </p>

      <Panel title="Metadata">
        <p>
          <span className="muted">Media kind:</span> {a.mediaKind ?? 'unknown'}
        </p>
        <p>
          <span className="muted">Size:</span>{' '}
          {a.observedSize != null ? formatBytes(a.observedSize) : '—'}
        </p>
        <p>
          <span className="muted">Source id:</span> {a.sourceId ?? '—'}
        </p>
        <p>
          <span className="muted">First seen:</span> {a.firstSeenAt}
        </p>
      </Panel>

      <Panel title="Replicas">
        <ReplicaTable overview={overview} />
      </Panel>

      <Panel title="Proxy state">
        <Chip tone={proxyTone(proxyReadiness(overview))}>{proxyReadiness(overview)}</Chip>
        {overview.derivatives.length > 0 ? (
          <ul>
            {overview.derivatives.map((d) => (
              <li key={d.id}>
                <code>{d.kind}</code> · {d.status} ({Math.round(d.readiness * 100)}%)
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No derivatives.</p>
        )}
      </Panel>

      <Panel title="Logical clips">
        {overview.clips.length === 0 ? (
          <p className="muted">Not part of any clip group.</p>
        ) : (
          <ul>
            {overview.clips.map((c) => (
              <li key={c.id}>
                {c.clipName} ·{' '}
                <Chip tone={c.resolved ? 'ok' : 'warn'}>{c.resolved ? 'resolved' : 'partial'}</Chip>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

import type { ReplicaSummary } from '../../../shared/ipc-methods.js';
import type { AssetOverview } from '../lib/asset.js';

function ReplicaTable({ overview }: { overview: AssetOverview }): JSX.Element {
  if (overview.replicas.length === 0) {
    return <p className="muted">No replicas recorded.</p>;
  }
  return (
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
            <td>{r.path}</td>
            <td>
              <Chip tone={replicaTone(replicaHealth(r))}>{replicaHealth(r)}</Chip>
            </td>
            <td className="muted">{r.verified ? 'verified' : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
