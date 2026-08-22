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
import { Chip, Panel, LoadingState, ErrorState, type Tone } from '../components/ui.js';
import {
  jobMatchesFilter,
  jobProgress,
  progressPercent,
  canCancel,
  canResume,
  canRetry,
  searchJobs,
  type JobFilter,
} from '../lib/activity.js';
import type { JobDetail } from '../../../shared/ipc-methods.js';

const FILTERS: JobFilter[] = ['all', 'active', 'attention', 'failed', 'finished'];

export function Activity(): JSX.Element {
  const jobs = useAsync(() => window.ferry.job.list());
  const [filter, setFilter] = useState<JobFilter>('all');
  const [query, setQuery] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [exportContent, setExportContent] = useState<string | null>(null);

  const list = jobs.data?.jobs ?? [];
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
    <div className="stack">
      <h2>Activity</h2>

      <Panel title="Filter & search">
        <div className="row">
          {FILTERS.map((f) => (
            <button
              key={f}
              className={`btn${filter === f ? ' btn--primary' : ''}`}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
          <input
            className="grow"
            type="search"
            aria-label="Search jobs"
            placeholder="Search command, project, state…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </Panel>

      {actionError !== null ? <Chip tone="danger">{actionError}</Chip> : null}

      <Panel title="Jobs">
        {filtered.length === 0 ? (
          <p className="muted">No jobs match.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Command</th>
                <th>State</th>
                <th>Progress</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => (
                <ActivityRow
                  key={j.id}
                  job={j}
                  onCancel={() => act(() => window.ferry.job.cancel(j.id))}
                  onResume={() => act(() => window.ferry.job.resume(j.id))}
                  onRetry={() => act(() => window.ferry.job.retry(j.id))}
                  onReceipt={() => exportReceipt(j.id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {exportContent !== null ? (
        <Panel title="Receipt">
          <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflowY: 'auto' }}>
            {exportContent}
          </pre>
          <button className="btn" onClick={() => setExportContent(null)}>
            Close
          </button>
        </Panel>
      ) : null}
    </div>
  );
}

function ActivityRow({
  job,
  onCancel,
  onResume,
  onRetry,
  onReceipt,
}: {
  job: JobDetail;
  onCancel: () => void;
  onResume: () => void;
  onRetry: () => void;
  onReceipt: () => void;
}): JSX.Element {
  return (
    <tr>
      <td>{job.command}</td>
      <td>
        <Chip tone={stateTone(job.state)}>{job.state}</Chip>
      </td>
      <td>
        <ProgressBar value={jobProgress(job)} label={`Progress for ${job.command}`} />
      </td>
      <td>
        <div className="row" style={{ gap: 4 }}>
          {canCancel(job) ? (
            <button className="btn btn--danger" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          {canResume(job) ? (
            <button className="btn" onClick={onResume}>
              Resume
            </button>
          ) : null}
          {canRetry(job) ? (
            <button className="btn" onClick={onRetry}>
              Retry
            </button>
          ) : null}
          {job.state === 'succeeded' ? (
            <button className="btn" onClick={onReceipt}>
              Receipt
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

/**
 * Job progress meter.
 *
 * Carries explicit `progressbar` semantics (WCAG 4.1.2) — without them a
 * screen reader sees two nested divs and announces nothing. `aria-valuetext`
 * gives the percentage a spoken form, and the label names which job the
 * meter belongs to so a table of them stays distinguishable.
 */
function ProgressBar({ value, label }: { value: number; label?: string }): JSX.Element {
  const pct = progressPercent(value);
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={`${pct}%`}
      aria-label={label ?? 'Job progress'}
      style={{
        width: 120,
        height: 8,
        background: 'var(--c-surface-2)',
        borderRadius: 4,
        overflow: 'hidden',
      }}
    >
      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--c-accent)' }} />
    </div>
  );
}

function stateTone(state: JobDetail['state']): Tone {
  if (['succeeded'].includes(state)) return 'ok';
  if (['failed'].includes(state)) return 'danger';
  if (['needs_attention', 'awaiting_review'].includes(state)) return 'attention';
  if (['queued', 'running', 'verifying', 'resumable'].includes(state)) return 'neutral';
  return 'neutral';
}
