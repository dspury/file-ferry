/**
 * Tests for the transfer dock's pure logic (R-4).
 *
 * These run in node without React/DOM. The one that matters most is that the
 * dock clears when a job settles *over the event stream* — the race R-4 calls
 * out: the dock must not keep claiming "running" after the run stopped.
 */
import { describe, expect, it } from 'vitest';
import {
  activeTransfers,
  dockCounters,
  dockPercent,
  dockStateLabel,
  etaSeconds,
  formatEta,
} from '../renderer/src/lib/dock.js';
import type { JobDetail, JobSnapshot } from '../shared/ipc-methods.js';

function job(over: Partial<JobDetail> = {}): JobDetail {
  return {
    id: 'job-1',
    projectId: null,
    sessionId: null,
    command: 'transfer',
    argsFingerprint: null,
    state: 'running',
    currentStep: 'transfer',
    totalSteps: 2,
    startedAt: '2026-09-15T00:00:00Z',
    updatedAt: '2026-09-15T00:01:00Z',
    finishedAt: null,
    error: null,
    resumable: false,
    ...over,
  };
}

function snapshot(over: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: 'job-1',
    state: 'running',
    currentStep: 'transfer',
    completedSteps: ['plan'],
    totalSteps: 2,
    startedAt: '2026-09-15T00:00:00Z',
    updatedAt: '2026-09-15T00:01:00Z',
    completedItems: 100,
    totalItems: 1000,
    bytesCopied: 100,
    totalBytes: 200,
    ...over,
  };
}

describe('activeTransfers', () => {
  it('keeps only in-flight transfer jobs, most recently updated first', () => {
    const jobs = [
      job({ id: 'old', updatedAt: '2026-09-15T00:00:01Z' }),
      job({ id: 'new', updatedAt: '2026-09-15T00:05:00Z' }),
      job({ id: 'queued', state: 'queued' }),
    ];
    const list = activeTransfers(jobs, new Map());
    expect(list.map((j) => j.id)).toEqual(['new', 'queued', 'old']);
  });

  it('excludes other commands, and jobs that are not moving', () => {
    const jobs = [
      job({ id: 'proxy', command: 'proxy' }),
      job({ id: 'stalled', state: 'resumable' }),
      job({ id: 'attention', state: 'needs_attention' }),
      job({ id: 'done', state: 'succeeded' }),
      job({ id: 'keep' }),
    ];
    expect(activeTransfers(jobs, new Map()).map((j) => j.id)).toEqual(['keep']);
  });

  it('clears a job that settled over the event stream, before any reload', () => {
    // The row still says running; the live snapshot says it finished.
    const jobs = [job({ id: 'a', state: 'running' })];
    const snapshots = new Map([['a', snapshot({ id: 'a', state: 'succeeded' })]]);
    expect(activeTransfers(jobs, snapshots)).toEqual([]);
  });
});

describe('etaSeconds / formatEta', () => {
  it('estimates from the average rate so far', () => {
    // 100 bytes in 60s -> 1.667 B/s; 100 bytes left -> 60s.
    expect(etaSeconds(snapshot({ bytesCopied: 100, totalBytes: 200 }))).toBe(60);
  });

  it('refuses to estimate without a total, bytes, or elapsed time', () => {
    expect(etaSeconds(null)).toBeNull();
    expect(etaSeconds(snapshot({ totalBytes: 0 }))).toBeNull();
    expect(etaSeconds(snapshot({ bytesCopied: 0 }))).toBeNull();
    expect(etaSeconds(snapshot({ startedAt: '2026-09-15T00:01:00Z' }))).toBeNull();
  });

  it('formats seconds, minutes, and hours', () => {
    expect(formatEta(45)).toBe('45s');
    expect(formatEta(60)).toBe('1m 0s');
    expect(formatEta(3725)).toBe('1h 2m');
  });
});

describe('dockCounters / dockPercent', () => {
  it('names files, bytes, and time left', () => {
    expect(dockCounters(snapshot())).toBe('100 / 1,000 files · 100 B of 200 B · 1m 0s left');
  });

  it('drops the parts the snapshot cannot supply', () => {
    expect(dockCounters(snapshot({ totalBytes: 0, bytesCopied: 0 }))).toBe('100 / 1,000 files');
    expect(dockCounters(null)).toBeNull();
  });

  it('measures bytes first, then items', () => {
    expect(dockPercent(snapshot({ bytesCopied: 150, totalBytes: 200 }))).toBe(75);
    expect(dockPercent(snapshot({ totalBytes: 0, completedItems: 250, totalItems: 1000 }))).toBe(
      25,
    );
    expect(dockPercent(null)).toBe(0);
  });
});

describe('dockStateLabel', () => {
  it('names the moving states', () => {
    expect(dockStateLabel('running')).toBe('Transferring');
    expect(dockStateLabel('queued')).toBe('Queued');
    expect(dockStateLabel('verifying')).toBe('Verifying');
  });
});
