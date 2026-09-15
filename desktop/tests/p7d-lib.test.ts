/**
 * Tests for the pure Package 7d Activity logic.
 * These run in node without React/DOM.
 */
import { describe, expect, it } from 'vitest';
import {
  jobMatchesFilter,
  jobProgress,
  canCancel,
  canResume,
  canRetry,
  canShowReceipt,
  searchJobs,
} from '../renderer/src/lib/activity.js';
import type { JobDetail } from '../shared/ipc-methods.js';

function job(id: string, state: string, totalSteps = 2): JobDetail {
  return {
    id,
    projectId: 'p1',
    sessionId: null,
    command: 'copy',
    argsFingerprint: null,
    state,
    currentStep: state === 'running' ? 'copy' : null,
    totalSteps,
    startedAt: null,
    updatedAt: '2026-08-12T17:30:00Z',
    finishedAt: null,
    error: null,
    resumable: state === 'resumable',
  };
}

describe('activity', () => {
  it('jobProgress never exceeds 1 and handles zero steps', () => {
    expect(jobProgress(job('a', 'running'))).toBe(0.5);
    expect(jobProgress(job('b', 'succeeded', 0))).toBe(0);
  });

  it('action gating', () => {
    expect(canCancel(job('a', 'running'))).toBe(true);
    expect(canCancel(job('b', 'succeeded'))).toBe(false);
    expect(canResume(job('c', 'needs_attention'))).toBe(true);
    expect(canResume(job('d', 'running'))).toBe(false);
    expect(canRetry(job('e', 'failed'))).toBe(true);
    expect(canRetry(job('f', 'succeeded'))).toBe(false);
  });

  it('offers the receipt for every terminal job, not only successes', () => {
    // The receipt for a failed or cancelled transfer names which replicas
    // verified before the run stopped -- the case an operator most needs
    // before deciding whether the card can be formatted.
    expect(canShowReceipt(job('a', 'succeeded'))).toBe(true);
    expect(canShowReceipt(job('b', 'failed'))).toBe(true);
    expect(canShowReceipt(job('c', 'cancelled'))).toBe(true);
    // A job still in flight has not written one yet.
    expect(canShowReceipt(job('d', 'running'))).toBe(false);
    expect(canShowReceipt(job('e', 'needs_attention'))).toBe(false);
  });

  it('jobMatchesFilter', () => {
    expect(jobMatchesFilter(job('a', 'running'), 'active')).toBe(true);
    expect(jobMatchesFilter(job('b', 'succeeded'), 'finished')).toBe(true);
    expect(jobMatchesFilter(job('c', 'failed'), 'failed')).toBe(true);
    expect(jobMatchesFilter(job('d', 'running'), 'all')).toBe(true);
  });

  it('searchJobs filters by command and state', () => {
    const jobs = [job('a', 'running'), job('b', 'failed')];
    expect(searchJobs(jobs, '')).toHaveLength(2);
    expect(searchJobs(jobs, 'copy')).toHaveLength(2);
    expect(searchJobs(jobs, 'failed')).toHaveLength(1);
    expect(searchJobs(jobs, 'zzz')).toHaveLength(0);
  });
});
