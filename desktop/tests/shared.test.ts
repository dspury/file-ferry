/**
 * Tests for the pure shared modules added in Package 6: native-picker
 * path validation, the reconnect replay store, and diagnostics helpers.
 * These run in vitest without Electron.
 */
import { describe, expect, it } from 'vitest';
import { sanitizePickedPath, type PickedPathInput } from '../shared/dialog.js';
import { isJobUpdatedParams, JobSnapshotStore, replayPayload } from '../shared/replay.js';
import { formatDiagnosticSummary, logDirectoryName } from '../shared/diagnostics.js';
import type { JobSnapshot } from '../shared/ipc-methods.js';

function snapshot(id: string, state: JobSnapshot['state']): JobSnapshot {
  return {
    id,
    state,
    currentStep: 'step',
    completedSteps: ['scan'],
    totalSteps: 2,
    startedAt: '2026-08-12T17:30:00Z',
    updatedAt: '2026-08-12T17:31:00Z',
  };
}

describe('sanitizePickedPath', () => {
  it('accepts an absolute path', () => {
    expect(sanitizePickedPath('/Volumes/RAID')).toBe('/Volumes/RAID');
  });

  it('accepts a windows drive path', () => {
    expect(sanitizePickedPath('D:\\media\\clips')).toBe('D:\\media\\clips');
  });

  it('rejects non-strings', () => {
    // Outside the declared PickedPathInput contract on purpose: the runtime
    // guard is defence in depth for a value crossing the IPC boundary, so a
    // non-string must still be rejected rather than trusted. `JSON.parse`
    // is typed `any`, which hands the function a genuine number at runtime
    // without needing a type assertion to get past the signature.
    const notAString: PickedPathInput = JSON.parse('123');
    expect(sanitizePickedPath(notAString)).toBeNull();
    expect(sanitizePickedPath(null)).toBeNull();
    expect(sanitizePickedPath(undefined)).toBeNull();
  });

  it('rejects empty and whitespace', () => {
    expect(sanitizePickedPath('')).toBeNull();
    expect(sanitizePickedPath('   ')).toBeNull();
  });

  it('rejects relative paths', () => {
    expect(sanitizePickedPath('clips')).toBeNull();
    expect(sanitizePickedPath('./clips')).toBeNull();
    expect(sanitizePickedPath('../media')).toBeNull();
  });

  it('rejects a bare root', () => {
    expect(sanitizePickedPath('/')).toBeNull();
    expect(sanitizePickedPath('C:\\')).toBeNull();
  });

  it('trims surrounding whitespace', () => {
    expect(sanitizePickedPath('  /Volumes/RAID  ')).toBe('/Volumes/RAID');
  });
});

describe('JobSnapshotStore', () => {
  it('records and returns the latest snapshot for a job', () => {
    const store = new JobSnapshotStore();
    store.record(snapshot('job-1', 'running'));
    store.record(snapshot('job-1', 'verifying'));
    const got = store.snapshotFor('job-1');
    expect(got?.state).toBe('verifying');
  });

  it('returns null for an unknown job', () => {
    const store = new JobSnapshotStore();
    expect(store.snapshotFor('nope')).toBeNull();
  });

  it('replays all snapshots in recency-descending order', () => {
    const store = new JobSnapshotStore();
    store.record(snapshot('job-1', 'running'));
    store.record(snapshot('job-2', 'succeeded'));
    const payload = replayPayload(store);
    expect(payload.map((s) => s.id)).toEqual(['job-2', 'job-1']);
  });

  it('evicts oldest entries past the bound', () => {
    const store = new JobSnapshotStore(2);
    store.record(snapshot('job-1', 'running'));
    store.record(snapshot('job-2', 'running'));
    store.record(snapshot('job-3', 'running'));
    expect(store.snapshotFor('job-1')).toBeNull();
    expect(store.snapshotFor('job-2')).not.toBeNull();
    expect(store.snapshotFor('job-3')).not.toBeNull();
  });

  it('clear empties the store', () => {
    const store = new JobSnapshotStore();
    store.record(snapshot('job-1', 'running'));
    store.clear();
    expect(store.all()).toHaveLength(0);
  });
});

describe('diagnostics helpers', () => {
  it('logDirectoryName is stable', () => {
    expect(logDirectoryName()).toBe('logs');
  });

  it('formats a diagnostic summary deterministically', () => {
    const summary = formatDiagnosticSummary({
      platform: 'darwin',
      electronVersion: '33.2.0',
      protocolVersion: 1,
      sidecarStatus: 'ready',
      dbPath: '/data/ferry.db',
      appDataDir: '/data',
      logDir: '/data/logs',
      logCount: 3,
    });
    expect(summary).toContain('platform=darwin');
    expect(summary).toContain('protocol=1');
    expect(summary).toContain('sidecar=ready');
    expect(summary).toContain('logCount=3');
  });
});

describe('isJobUpdatedParams', () => {
  // The shape the sidecar actually emits: service/protocol.py JobUpdatedEvent
  // is `{ jobId, snapshot }`, and JobSnapshot carries a string `id`.
  const snapshot = {
    id: 'job-1',
    state: 'running',
    currentStep: 'copy',
    completedSteps: ['probe'],
    totalSteps: 4,
    startedAt: '2026-08-22T00:00:00Z',
    updatedAt: '2026-08-22T00:00:01Z',
  };

  it('accepts a real job.updated payload', () => {
    expect(isJobUpdatedParams({ jobId: 'job-1', snapshot })).toBe(true);
  });

  it('accepts the snapshot even when other fields are absent', () => {
    // The guard deliberately checks only what the store needs (a keyed id);
    // it is not a full schema validator.
    expect(isJobUpdatedParams({ snapshot: { id: 'job-2' } })).toBe(true);
  });

  it('rejects payloads with no snapshot', () => {
    expect(isJobUpdatedParams({ jobId: 'job-1' })).toBe(false);
  });

  it('rejects a snapshot with no usable id', () => {
    expect(isJobUpdatedParams({ snapshot: {} })).toBe(false);
    expect(isJobUpdatedParams({ snapshot: { id: '' } })).toBe(false);
    expect(isJobUpdatedParams({ snapshot: { id: 42 } })).toBe(false);
    expect(isJobUpdatedParams({ snapshot: null })).toBe(false);
  });

  it('rejects non-object payloads', () => {
    expect(isJobUpdatedParams(null)).toBe(false);
    expect(isJobUpdatedParams('job-1')).toBe(false);
    expect(isJobUpdatedParams(7)).toBe(false);
  });

  it('feeds the snapshot store, which is what the guard gates', () => {
    const params = { jobId: 'job-1', snapshot };
    const store = new JobSnapshotStore();
    if (isJobUpdatedParams(params)) store.record(params.snapshot);
    expect(store.snapshotFor('job-1')?.id).toBe('job-1');
  });
});
