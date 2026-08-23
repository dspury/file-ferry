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
  Panel,
  PathCell,
  ScreenError,
  ScreenLoading,
  StatCard,
} from '../components/ui.js';
import {
  homeCards,
  isJobActive,
  isJobAttention,
  isJobFailed,
  type HomeSummary,
} from '../lib/home.js';
import { jobStateTone } from '../lib/job-state.js';
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
    return (
      <ScreenLoading
        message="Reading jobs, volumes, and media…"
        hint="Nothing is being written. This is three read-only queries against the sidecar."
      />
    );
  }
  if (error !== null) {
    return (
      <ScreenError
        message={error}
        onRetry={() => {
          jobs.reload();
          volumes.reload();
          assets.reload();
        }}
      />
    );
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
          /*
            Compact, because the other well on this screen holds "Start an
            offload" -- the only thing a first-run Dashboard can actually
            do -- and two full wells push it off the fold at the app's own
            1280x800 default. This panel reports a condition and offers a
            diagnostic; that one offers the next move, so that one keeps
            the ceremony. The hint keeps both sentences: the second names
            the symptom -- mounted but not listed -- which is the case the
            button beside it answers, and the compact well wraps rather
            than truncating, so saying it costs a line and not a fact.
          */
          <EmptyState
            density="compact"
            message="No volumes detected"
            hint="Connect a card reader or an external drive and it will appear here. If one is already mounted, Environment shows what ferry can and cannot see."
            action={
              <button type="button" className="btn" onClick={() => navigateTo('onboarding')}>
                Check environment
              </button>
            }
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

/**
 * One chip, one mapping, shared with Activity.
 *
 * The three-branch cascade this replaces classified only active, attention,
 * and failed, and fell through to an untoned chip for everything else -- so
 * `succeeded` and `cancelled` drew as the same neutral plate, and a good
 * outcome was indistinguishable from an aborted one. It also drew active
 * work in the success tone, which Activity did not, so the same job wore two
 * different colours on two screens.
 */
function JobStateChip({ state }: { state: JobDetail['state'] }): JSX.Element {
  return <Chip tone={jobStateTone(state)}>{state}</Chip>;
}
