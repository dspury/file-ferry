/**
 * Pure Activity-screen logic (testable without React/DOM).
 *
 * Activity shows running / finished / attention jobs, per-step progress,
 * safe cancel/retry/resume, and searchable receipts (plan §8.2).
 * Job-state transitions and search are derived here.
 */
import type { JobDetail, ExportReceiptResult } from '../../../shared/ipc-methods.js';

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

/** Receipt export content is non-empty (a successful export has content). */
export function receiptExportOk(result: ExportReceiptResult | null): boolean {
  if (result === null) return false;
  return result.content.trim().length > 0;
}
