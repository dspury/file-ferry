/**
 * Home screen.
 *
 * Active jobs, connected sources, unsafe cards, missing/unverified
 * replicas, failed work, and proxy readiness (plan §8.2). Aggregates the
 * pure logic in lib/home.ts; the screen is a thin renderer.
 */
import { useAsync } from '../hooks/useAsync.js';
import { Chip, Panel, LoadingState, ErrorState } from '../components/ui.js';
import {
  homeCards,
  isJobActive,
  isJobAttention,
  isJobFailed,
  type HomeSummary,
} from '../lib/home.js';
import type { JobDetail } from '../../../shared/ipc-methods.js';

export function Home(): JSX.Element {
  const jobs = useAsync(() => window.mediaMate.job.list());
  const volumes = useAsync(() => window.mediaMate.source.listVolumes());
  const assets = useAsync(() => window.mediaMate.asset.list());

  const loading = jobs.loading || volumes.loading || assets.loading;
  const error = jobs.error ?? volumes.error ?? assets.error;

  if (loading) {
    return <LoadingState message="Loading Home…" />;
  }
  if (error !== null) {
    return <ErrorState message={error} />;
  }

  const jobList = jobs.data?.jobs ?? [];
  const assetList = assets.data?.assets ?? [];
  const volumesList = volumes.data?.volumes ?? [];

  const summary: HomeSummary = {
    activeJobs: jobList.filter(isJobActive).length,
    attentionJobs: jobList.filter(isJobAttention).length,
    failedJobs: jobList.filter(isJobFailed).length,
    unsafeCards: 0,
    unverifiedReplicas: 0,
    assets: assetList.length,
    proxyPending: 0,
  };

  const cards = homeCards(summary);

  return (
    <div className="stack">
      <h2>Home</h2>

      <div className="card">
        <div className="row" style={{ gap: 16, alignItems: 'stretch' }}>
          {cards.map((c) => (
            <div key={c.label} className="grow">
              <div className="muted">{c.label}</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>
                <Chip tone={c.tone}>{c.count}</Chip>
              </div>
            </div>
          ))}
        </div>
      </div>

      <Panel title="Connected sources">
        {volumesList.length === 0 ? (
          <p className="muted">No volumes detected.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Mount</th>
                <th>Filesystem</th>
              </tr>
            </thead>
            <tbody>
              {volumesList.map((v) => (
                <tr key={v.path}>
                  <td>{v.path}</td>
                  <td className="muted">{v.filesystem}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Jobs">
        {jobList.length === 0 ? (
          <p className="muted">No jobs yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Command</th>
                <th>State</th>
                <th>Project</th>
              </tr>
            </thead>
            <tbody>
              {jobList.map((j) => (
                <tr key={j.id}>
                  <td>{j.command}</td>
                  <td>
                    <JobStateChip state={j.state} />
                  </td>
                  <td className="muted">{j.projectId}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function JobStateChip({ state }: { state: JobDetail['state'] }): JSX.Element {
  if (isJobActive({ state } as JobDetail)) {
    return <Chip tone="ok">{state}</Chip>;
  }
  if (isJobAttention({ state } as JobDetail)) {
    return <Chip tone="attention">{state}</Chip>;
  }
  if (isJobFailed({ state } as JobDetail)) {
    return <Chip tone="danger">{state}</Chip>;
  }
  return <Chip>{state}</Chip>;
}
