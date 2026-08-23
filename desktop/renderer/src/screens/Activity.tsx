/**
 * Activity screen.
 *
 * Running / finished / attention jobs with per-step progress, safe
 * cancel / retry / resume, and searchable receipts (plan §8.2). Job
 * actions are gated on real state (canCancel/canResume/canRetry); the UI
 * reflects the sidecar result, never an optimistic transition.
 */
import { useState } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import { useJobStream } from '../hooks/useJobStream.js';
import {
  Banner,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
  Progress,
  SegmentedControl,
  type Tone,
} from '../components/ui.js';
import {
  jobMatchesFilter,
  liveProgress,
  mergeJobSnapshot,
  progressLabel,
  progressPercent,
  canCancel,
  canResume,
  canRetry,
  canShowReceipt,
  searchJobs,
  type JobFilter,
} from '../lib/activity.js';
import type { JobDetail, JobSnapshot } from '../../../shared/ipc-methods.js';

const FILTERS: readonly JobFilter[] = ['all', 'active', 'attention', 'failed', 'finished'];

export function Activity(): JSX.Element {
  const jobs = useAsync(() => window.ferry.job.list());
  const [filter, setFilter] = useState<JobFilter>('all');
  const [query, setQuery] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [exportContent, setExportContent] = useState<string | null>(null);

  const raw = jobs.data?.jobs ?? [];

  // A job that appears only in an event (created on the Offload screen, or
  // by a recovery sweep) cannot be rendered from its snapshot alone, so the
  // stream asks for a fresh list instead. `reload` is already stable.
  const stream = useJobStream(raw, jobs.reload);

  // Filtering and searching run on the *live* rows, so a job that finishes
  // while you are watching leaves the "active" filter on its own.
  const list = raw.map((job) => mergeJobSnapshot(job, stream.snapshots.get(job.id) ?? null));
  const filtered = searchJobs(list, query).filter((j) => jobMatchesFilter(j, filter));

  const act = async <T,>(fn: () => Promise<T>) => {
    setActionError(null);
    try {
      await fn();
      jobs.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  };

  const exportReceipt = async (operationId: string) => {
    setActionError(null);
    try {
      const result = await window.ferry.receipt.export({
        operationId,
        format: 'markdown',
      });
      setExportContent(result.content);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  };

  if (jobs.loading) {
    return <LoadingState message="Loading activity…" />;
  }
  if (jobs.error !== null) {
    return <ErrorState message={jobs.error} />;
  }

  return (
    <div className="page">
      {actionError !== null ? <Banner tone="danger">{actionError}</Banner> : null}

      <Panel
        title="Jobs"
        description={
          filtered.length === list.length
            ? `${list.length} total`
            : `${filtered.length} of ${list.length}`
        }
        actions={
          <>
            {stream.subscribed > 0 ? (
              <Chip tone="ok">Live · {stream.subscribed} watched</Chip>
            ) : null}
            {/*
              A search input needs no visible label here: it sits in a
              toolbar with a placeholder and an aria-label, and a "Search"
              caption beside it would only cost horizontal room. The
              segmented control carries its own group label.
            */}
            <SegmentedControl
              label="Filter jobs by state"
              value={filter}
              options={FILTERS}
              onChange={setFilter}
            />
            <input
              type="search"
              className="toolbar__search"
              aria-label="Search jobs"
              placeholder="Search command, project, state…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </>
        }
        flush={filtered.length > 0}
      >
        {filtered.length === 0 ? (
          <EmptyState
            message={list.length === 0 ? 'No jobs yet' : 'No jobs match'}
            hint={
              list.length === 0
                ? 'Offloads and organize runs show up here as soon as they are created.'
                : 'Try a different filter or clear the search.'
            }
            action={
              list.length === 0 || (filter === 'all' && query === '') ? undefined : (
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setFilter('all');
                    setQuery('');
                  }}
                >
                  Clear filters
                </button>
              )
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Command</th>
                  <th>State</th>
                  <th>Progress</th>
                  <th className="cell-actions">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((j) => (
                  <ActivityRow
                    key={j.id}
                    job={j}
                    snapshot={stream.snapshots.get(j.id) ?? null}
                    onCancel={() => act(() => window.ferry.job.cancel(j.id))}
                    onResume={() => act(() => window.ferry.job.resume(j.id))}
                    onRetry={() => act(() => window.ferry.job.retry(j.id))}
                    onReceipt={() => exportReceipt(j.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {exportContent !== null ? (
        <Panel
          title="Receipt"
          description="The durable record of what was written and verified"
          actions={
            <button type="button" className="btn btn--sm" onClick={() => setExportContent(null)}>
              Close
            </button>
          }
        >
          <pre className="pre pre--tall">{exportContent}</pre>
        </Panel>
      ) : null}
    </div>
  );
}

function ActivityRow({
  job,
  snapshot,
  onCancel,
  onResume,
  onRetry,
  onReceipt,
}: {
  job: JobDetail;
  snapshot: JobSnapshot | null;
  onCancel: () => void;
  onResume: () => void;
  onRetry: () => void;
  onReceipt: () => void;
}): JSX.Element {
  const detail = snapshot === null ? null : progressLabel(snapshot);
  return (
    <tr>
      <td>{job.command}</td>
      <td>
        <Chip tone={stateTone(job.state)}>{job.state}</Chip>
        {/* The step is the only thing that says *what* the job is doing;
            without it a long verify pass looks identical to a stall. */}
        {job.currentStep === null || job.currentStep === '' ? null : (
          <div className="muted">{job.currentStep}</div>
        )}
      </td>
      <td>
        <Progress
          percent={progressPercent(liveProgress(job, snapshot))}
          label={`Progress for ${job.command}`}
          tone={progressTone(job.state)}
        />
        {/* A percentage alone does not say whether a slow job is moving or
            how much is left. The byte count does. */}
        {detail === null ? null : <div className="muted">{detail}</div>}
      </td>
      <td className="cell-actions">
        <div className="row">
          {canCancel(job) ? (
            <button type="button" className="btn btn--danger btn--sm" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          {canResume(job) ? (
            <button type="button" className="btn btn--sm" onClick={onResume}>
              Resume
            </button>
          ) : null}
          {canRetry(job) ? (
            <button type="button" className="btn btn--sm" onClick={onRetry}>
              Retry
            </button>
          ) : null}
          {canShowReceipt(job) ? (
            <button type="button" className="btn btn--sm" onClick={onReceipt}>
              Receipt
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function stateTone(state: JobDetail['state']): Tone {
  if (['succeeded'].includes(state)) return 'ok';
  if (['failed'].includes(state)) return 'danger';
  if (['needs_attention', 'awaiting_review'].includes(state)) return 'attention';
  if (['queued', 'running', 'verifying', 'resumable'].includes(state)) return 'neutral';
  return 'neutral';
}

/** The bar echoes the row's outcome so a finished table can be read down
 *  the progress column alone. */
function progressTone(state: JobDetail['state']): 'neutral' | 'ok' | 'danger' {
  if (state === 'succeeded') return 'ok';
  if (state === 'failed') return 'danger';
  return 'neutral';
}
