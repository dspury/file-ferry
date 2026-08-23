/**
 * Tests for the pure Package 7d logic (Ingest, Organize, Activity).
 * These run in node without React/DOM.
 */
import { describe, expect, it } from 'vitest';
import {
  ingestStage,
  planReviewable,
  planBlocked,
  sourceReady,
  capacityLabel,
  destinationKinds,
} from '../renderer/src/lib/ingest.js';
import {
  organizeStage,
  previewApplyable,
  collisionBlocks,
  moveRequiresConfirm,
  outcomeSummary,
  collisionCount,
} from '../renderer/src/lib/organize.js';
import {
  jobMatchesFilter,
  jobProgress,
  canCancel,
  canResume,
  canRetry,
  canShowReceipt,
  searchJobs,
} from '../renderer/src/lib/activity.js';
import type { IntakePlan, JobDetail, OrganizePreview } from '../shared/ipc-methods.js';

function plan(over: Partial<IntakePlan> = {}): IntakePlan {
  return {
    fingerprint: 'fp',
    projectId: 'p1',
    sourceId: 1,
    sourceRoot: '/src',
    destinations: [{ kind: 'working', rootPath: '/w' }],
    entries: [{ relPath: 'a.mov', destPath: '/w/a.mov', size: 10 }],
    totalBytes: 10,
    capacityOk: true,
    neededBytes: 0,
    warnings: [],
    collisions: [],
    ...over,
  };
}

function preview(over: Partial<OrganizePreview> = {}): OrganizePreview {
  return {
    sourceRoot: '/src',
    destRoot: '/dst',
    entries: [{ sourcePath: '/src/a.mov', destPath: '/dst/a.mov', size: 10 }],
    collisions: [],
    totalBytes: 10,
    mode: 'copy',
    ...over,
  };
}

function job(id: string, state: string, totalSteps = 2): JobDetail {
  return {
    id,
    projectId: 'p1',
    sessionId: null,
    command: 'copy',
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

describe('ingest', () => {
  it('planReviewable requires destinations and entries', () => {
    expect(planReviewable(plan())).toBe(true);
    expect(planReviewable(plan({ destinations: [] }))).toBe(false);
    expect(planReviewable(plan({ entries: [] }))).toBe(false);
    expect(planReviewable(null)).toBe(false);
  });

  it('planBlocked when capacity fails', () => {
    expect(planBlocked(plan({ capacityOk: false }))).toBe(true);
    expect(planBlocked(plan())).toBe(false);
    expect(planBlocked(null)).toBe(true);
  });

  it('sourceReady requires entries', () => {
    expect(
      sourceReady({
        entries: [{ path: 'a', size: 1, mtime: 0 }],
        sourceId: 1,
        rootPath: '/',
        kind: 'card',
        label: null,
        fileCount: 1,
        totalBytes: 1,
        manifestHash: 'x',
      }),
    ).toBe(true);
    expect(sourceReady(null)).toBe(false);
  });

  it('ingestStage gates on real data, never optimistic', () => {
    const source = {
      entries: [{ path: 'a', size: 1, mtime: 0 }],
      sourceId: 1,
      rootPath: '/',
      kind: 'card',
      label: null,
      fileCount: 1,
      totalBytes: 1,
      manifestHash: 'x',
    };
    expect(ingestStage({ source: null, plan: null, executing: false, done: false })).toBe('source');
    expect(ingestStage({ source, plan: null, executing: false, done: false })).toBe('plan');
    expect(ingestStage({ source, plan: plan(), executing: false, done: false })).toBe('ready');
    expect(ingestStage({ source, plan: plan(), executing: true, done: false })).toBe('running');
    expect(ingestStage({ source, plan: plan(), executing: false, done: true })).toBe('done');
  });

  it('capacityLabel and destinationKinds', () => {
    expect(capacityLabel(plan())).toBe('capacity ok');
    expect(capacityLabel(plan({ capacityOk: false, neededBytes: 500 }))).toContain('500 B');
    expect(destinationKinds(plan().destinations)).toEqual(['working']);
  });
});

describe('organize', () => {
  it('previewApplyable rejects collisions', () => {
    expect(previewApplyable(preview())).toBe(true);
    expect(
      previewApplyable(preview({ collisions: [{ path: 'a', reason: 'dup', count: 2 }] })),
    ).toBe(false);
    expect(previewApplyable(null)).toBe(false);
  });

  it('collisionBlocks gates on real data', () => {
    expect(collisionBlocks(preview())).toBe(false);
    expect(collisionBlocks(preview({ collisions: [{ path: 'a', reason: 'dup', count: 1 }] }))).toBe(
      true,
    );
    expect(collisionBlocks(null)).toBe(true);
  });

  it('moveRequiresConfirm only gates move', () => {
    expect(moveRequiresConfirm('copy', false)).toBe(false);
    expect(moveRequiresConfirm('link', false)).toBe(false);
    expect(moveRequiresConfirm('move', false)).toBe(true);
    expect(moveRequiresConfirm('move', true)).toBe(false);
  });

  it('outcomeSummary counts real rows (no optimistic)', () => {
    expect(
      outcomeSummary([
        { sourcePath: 'a', destPath: 'b', operation: 'copy', ok: true, error: null },
        { sourcePath: 'c', destPath: 'd', operation: 'copy', ok: false, error: 'x' },
      ]),
    ).toEqual({ ok: 1, failed: 1, total: 2 });
  });

  it('collisionCount sums counts', () => {
    expect(
      collisionCount([
        { path: 'a', reason: 'x', count: 2 },
        { path: 'b', reason: 'y', count: 3 },
      ]),
    ).toBe(5);
  });

  it('organizeStage gates', () => {
    expect(organizeStage({ sourceEntries: 0, preview: null, executing: false, done: false })).toBe(
      'source',
    );
    expect(organizeStage({ sourceEntries: 2, preview: null, executing: false, done: false })).toBe(
      'preview',
    );
    expect(
      organizeStage({ sourceEntries: 2, preview: preview(), executing: false, done: false }),
    ).toBe('ready');
    expect(
      organizeStage({ sourceEntries: 2, preview: preview(), executing: true, done: false }),
    ).toBe('running');
    expect(
      organizeStage({ sourceEntries: 2, preview: preview(), executing: false, done: true }),
    ).toBe('done');
  });
});

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
    // The receipt for a failed or cancelled offload names which replicas
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
