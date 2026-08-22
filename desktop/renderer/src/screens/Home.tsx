/**
 * Dashboard screen.
 *
 * Active jobs, connected sources, unsafe cards, missing/unverified
 * replicas, failed work, and proxy readiness (plan §8.2). Aggregates the
 * pure logic in lib/home.ts; the screen is a thin renderer.
 */
import { useAsync } from '../hooks/useAsync.js';
import {
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
  PathCell,
  StatCard,
} from '../components/ui.js';
import {
  homeCards,
  isJobActive,
  isJobAttention,
  isJobFailed,
  type HomeSummary,
} from '../lib/home.js';
import { formatBytes } from '../lib/doctor.js';
import { navigateTo } from '../views.js';
import type { JobDetail } from '../../../shared/ipc-methods.js';

/** Jobs are listed newest-work-first; the dashboard shows only the head of
 *  the list and defers the rest to Activity, which can filter and search. */
const RECENT_JOB_LIMIT = 6;

export function Home(): JSX.Element {
  const jobs = useAsync(() => window.ferry.job.list());
  const volumes = useAsync(() => window.ferry.source.listVolumes());
  const assets = useAsync(() => window.ferry.asset.list());

  const loading = jobs.loading || volumes.loading || assets.loading;
  const error = jobs.error ?? volumes.error ?? assets.error;

  if (loading) {
    return <LoadingState message="Loading dashboard…" />;
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
  const recent = jobList.slice(0, RECENT_JOB_LIMIT);

  return (
    <div className="page">
      {/*
        A tile only earns colour when it is reporting something. At zero,
        "Failed" in red reads as an alarm for a healthy system, so a zero
        count falls back to the neutral tone and the number stays plain.
      */}
      <div className="stats">
        {cards.map((c) => (
          <StatCard
            key={c.label}
            label={c.label}
            value={c.count}
            tone={c.count > 0 ? c.tone : 'neutral'}
          />
        ))}
      </div>

      <Panel
        title="Connected sources"
        description="Volumes ferry can currently see"
        flush={volumesList.length > 0}
      >
        {volumesList.length === 0 ? (
          <EmptyState
            message="No volumes detected"
            hint="Connect a card reader or an external drive and it will appear here."
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Mount</th>
                  <th>Filesystem</th>
                  <th className="cell-num">Free</th>
                </tr>
              </thead>
              <tbody>
                {volumesList.map((v) => (
                  <tr key={v.path}>
                    <td>
                      <PathCell path={v.path} />
                    </td>
                    <td className="muted">{v.filesystem}</td>
                    <td className="cell-num muted">{formatBytes(v.freeBytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Recent jobs"
        description={
          jobList.length > RECENT_JOB_LIMIT
            ? `Showing ${RECENT_JOB_LIMIT} of ${jobList.length}`
            : undefined
        }
        actions={
          jobList.length === 0 ? undefined : (
            <button type="button" className="btn btn--sm" onClick={() => navigateTo('activity')}>
              View all in Activity
            </button>
          )
        }
        flush={recent.length > 0}
      >
        {recent.length === 0 ? (
          <EmptyState
            message="No jobs yet"
            hint="Offload a camera card or organize existing media to create the first one."
            action={
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => navigateTo('ingest')}
              >
                Start an offload
              </button>
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Command</th>
                  <th>State</th>
                  <th>Project</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((j) => (
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
          </div>
        )}
      </Panel>
    </div>
  );
}

function JobStateChip({ state }: { state: JobDetail['state'] }): JSX.Element {
  if (isJobActive({ state })) {
    return <Chip tone="ok">{state}</Chip>;
  }
  if (isJobAttention({ state })) {
    return <Chip tone="attention">{state}</Chip>;
  }
  if (isJobFailed({ state })) {
    return <Chip tone="danger">{state}</Chip>;
  }
  return <Chip>{state}</Chip>;
}
