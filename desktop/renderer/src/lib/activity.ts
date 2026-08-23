/**
 * Pure Activity-screen logic (testable without React/DOM).
 *
 * Activity shows running / finished / attention jobs, per-step progress,
 * safe cancel/retry/resume, and searchable receipts (plan §8.2).
 * Job-state transitions and search are derived here.
 */
import { formatBytes, formatCount } from './format.js';
import type { JobDetail, ExportReceiptResult, JobSnapshot } from '../../../shared/ipc-methods.js';

export type JobFilter = 'all' | 'active' | 'attention' | 'failed' | 'finished';

export const ACTIVE_STATES = new Set(['queued', 'running', 'verifying', 'resumable']);
export const ATTENTION_STATES = new Set(['needs_attention', 'awaiting_review']);
export const FINISHED_STATES = new Set(['succeeded', 'failed', 'cancelled']);

export function jobMatchesFilter(job: JobDetail, filter: JobFilter): boolean {
  switch (filter) {
    case 'all':
      return true;
    case 'active':
      return ACTIVE_STATES.has(job.state);
    case 'attention':
      return ATTENTION_STATES.has(job.state);
    case 'failed':
      return job.state === 'failed';
    case 'finished':
      return FINISHED_STATES.has(job.state);
  }
}

/** Per-step progress (0..1), never over 1 even on partial data. */
export function jobProgress(job: JobDetail): number {
  if (job.totalSteps <= 0) return 0;
  const completed = job.currentStep ? 1 : 0;
  return Math.min(1, Math.max(0, completed / job.totalSteps));
}

/**
 * Render a 0..1 progress fraction as an integer percentage for ARIA.
 *
 * `aria-valuenow` must be a real number in [valuemin, valuemax]; an
 * out-of-range fraction would otherwise reach the accessibility tree. Only
 * NaN needs its own guard — it survives Math.min/max, whereas the
 * infinities clamp to the ends like any other out-of-range value.
 */
export function progressPercent(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.round(Math.min(1, Math.max(0, value)) * 100);
}

/** A job is safe to cancel when it is actively running/queued/verifying. */
export function canCancel(job: JobDetail): boolean {
  return ACTIVE_STATES.has(job.state);
}

/** A job is safe to resume when it needs attention. */
export function canResume(job: JobDetail): boolean {
  return job.state === 'needs_attention';
}

/** A failed job can be retried. */
export function canRetry(job: JobDetail): boolean {
  return job.state === 'failed';
}

/** Search a job by command, project id, or state (case-insensitive). */
export function searchJobs(jobs: readonly JobDetail[], query: string): JobDetail[] {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return [...jobs];
  return jobs.filter((j) => {
    return (
      j.command.toLowerCase().includes(q) ||
      j.projectId.toLowerCase().includes(q) ||
      j.state.toLowerCase().includes(q) ||
      (j.error ?? '').toLowerCase().includes(q)
    );
  });
}

/**
 * The jobs worth holding a live subscription for.
 *
 * A finished job will never emit again, so subscribing to one costs a
 * round trip and buys nothing. Everything else can still move — including
 * `planned` and `awaiting_review`, which is exactly the transition an
 * operator is waiting on after creating an offload.
 */
export function streamableJobIds(jobs: readonly JobDetail[]): string[] {
  return jobs.filter((job) => !FINISHED_STATES.has(job.state)).map((job) => job.id);
}

/**
 * Fold a live snapshot into the job row it belongs to.
 *
 * Returns the original row unchanged when the snapshot is for another job
 * or is older than what the row already shows — events can arrive out of
 * order after a reconnect replay, and a late one must not roll a job's
 * state backwards. ISO-8601 timestamps compare correctly as strings.
 *
 * Only the fields a snapshot actually carries are taken; `command`,
 * `projectId`, and `error` are not in a snapshot, so they keep whatever
 * `job.list` last returned rather than being blanked.
 */
export function mergeJobSnapshot(job: JobDetail, snapshot: JobSnapshot | null): JobDetail {
  if (snapshot === null || snapshot.id !== job.id) return job;
  if (snapshot.updatedAt < job.updatedAt) return job;
  return {
    ...job,
    state: snapshot.state,
    currentStep: snapshot.currentStep,
    totalSteps: snapshot.totalSteps,
    startedAt: snapshot.startedAt,
    updatedAt: snapshot.updatedAt,
  };
}

/**
 * Progress from a live snapshot, using the finest measure available.
 *
 * Bytes first: a card is a handful of very large files, so a file count
 * jumps in visible steps while bytes move continuously. Items next, for a
 * runner that cannot report bytes (transcoding gives no usable output
 * size). Steps last, and only as a coarse phase indicator — an offload has
 * two of them, so on its own it would read 0%, 50%, 100% for a job that
 * spends an hour inside the second one.
 */
export function snapshotProgress(snapshot: JobSnapshot): number {
  if (snapshot.totalBytes > 0) return clampFraction(snapshot.bytesCopied / snapshot.totalBytes);
  if (snapshot.totalItems > 0) return clampFraction(snapshot.completedItems / snapshot.totalItems);
  if (snapshot.totalSteps > 0) {
    return clampFraction(snapshot.completedSteps.length / snapshot.totalSteps);
  }
  return 0;
}

function clampFraction(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/**
 * The count beside the bar: what a percentage alone cannot tell you.
 *
 * "1.2 GB of 4.0 GB" says whether a stalled-looking job is moving at all,
 * and how much is left — the number an operator deciding whether to wait
 * actually needs. Returns null when the snapshot carries no counters.
 */
export function progressLabel(snapshot: JobSnapshot): string | null {
  if (snapshot.totalBytes > 0) {
    return `${formatBytes(snapshot.bytesCopied)} of ${formatBytes(snapshot.totalBytes)}`;
  }
  if (snapshot.totalItems > 0) {
    return `${formatCount(snapshot.completedItems)} of ${formatCount(snapshot.totalItems)} files`;
  }
  return null;
}

/** Best available progress for a row: the live snapshot if there is one. */
export function liveProgress(job: JobDetail, snapshot: JobSnapshot | null): number {
  return snapshot === null ? jobProgress(job) : snapshotProgress(snapshot);
}

/** Receipt export content is non-empty (a successful export has content). */
export function receiptExportOk(result: ExportReceiptResult | null): boolean {
  if (result === null) return false;
  return result.content.trim().length > 0;
}
