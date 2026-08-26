/**
 * Tests for the follow-up work after the UI refinement pass: hash routing
 * with parameters, live job-snapshot folding, and the Media browser's list
 * helpers. All pure — no React, no DOM.
 */
import { describe, expect, it } from 'vitest';
import { parseRoute, routeHash } from '../renderer/src/views.js';
import {
  liveProgress,
  mergeJobSnapshot,
  progressLabel,
  snapshotProgress,
  streamableJobIds,
} from '../renderer/src/lib/activity.js';
import {
  assetFileName,
  isCompleteAsset,
  searchAssets,
  sortAssets,
} from '../renderer/src/lib/asset.js';
import { jobUpdatedFrame } from '../shared/replay.js';
import type { AssetSummary, JobDetail, JobSnapshot } from '../shared/ipc-methods.js';

function job(over: Partial<JobDetail> = {}): JobDetail {
  return {
    id: 'j1',
    projectId: 'p1',
    sessionId: null,
    command: 'offload',
    state: 'running',
    currentStep: 'copy',
    totalSteps: 4,
    startedAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:10Z',
    finishedAt: null,
    error: null,
    resumable: false,
    ...over,
  };
}

function snapshot(over: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: 'j1',
    state: 'running',
    currentStep: 'verify',
    completedSteps: ['copy', 'checksum'],
    totalSteps: 4,
    startedAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:20Z',
    completedItems: 0,
    totalItems: 0,
    bytesCopied: 0,
    totalBytes: 0,
    ...over,
  };
}

function asset(over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: 'a1',
    sourceId: 1,
    sourceRelativePath: 'PRIVATE/M4ROOT/CLIP/C0001.MP4',
    observedSize: 1_000,
    observedMtime: null,
    lifecycleState: 'adopted',
    mediaKind: 'video',
    firstSeenAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('parseRoute', () => {
  it('reads the view id from a bare route', () => {
    expect(parseRoute('#/activity', 'home')).toEqual({ viewId: 'activity', params: new Map() });
  });

  it('falls back to the default for an empty or unparseable hash', () => {
    expect(parseRoute('', 'home').viewId).toBe('home');
    expect(parseRoute('#nonsense', 'home').viewId).toBe('home');
    // A trailing path segment is not the shape this router uses; it must not
    // silently resolve to a view with the segment ignored.
    expect(parseRoute('#/asset/extra', 'home').viewId).toBe('home');
  });

  it('reads query parameters', () => {
    const route = parseRoute('#/asset?id=a1&project=p1', 'home');
    expect(route.viewId).toBe('asset');
    expect(route.params.get('id')).toBe('a1');
    expect(route.params.get('project')).toBe('p1');
  });

  it('keeps the first value of a repeated key', () => {
    expect(parseRoute('#/asset?id=first&id=second', 'home').params.get('id')).toBe('first');
  });

  it('decodes percent-encoded values', () => {
    expect(parseRoute('#/asset?project=a%20b', 'home').params.get('project')).toBe('a b');
  });

  it('round-trips through routeHash', () => {
    const hash = routeHash('asset', { id: 'a1', project: 'p 1' });
    const route = parseRoute(hash, 'home');
    expect(route.viewId).toBe('asset');
    expect(route.params.get('id')).toBe('a1');
    expect(route.params.get('project')).toBe('p 1');
  });
});

describe('routeHash', () => {
  it('omits the query string when there are no params', () => {
    expect(routeHash('home')).toBe('#/home');
    expect(routeHash('home', {})).toBe('#/home');
  });
});

describe('streamableJobIds', () => {
  it('subscribes to anything that can still move', () => {
    const jobs = [
      job({ id: 'a', state: 'planned' }),
      job({ id: 'b', state: 'running' }),
      job({ id: 'c', state: 'awaiting_review' }),
    ];
    expect(streamableJobIds(jobs)).toEqual(['a', 'b', 'c']);
  });

  it('skips finished jobs, which will never emit again', () => {
    const jobs = [
      job({ id: 'a', state: 'succeeded' }),
      job({ id: 'b', state: 'failed' }),
      job({ id: 'c', state: 'cancelled' }),
      job({ id: 'd', state: 'running' }),
    ];
    expect(streamableJobIds(jobs)).toEqual(['d']);
  });
});

describe('mergeJobSnapshot', () => {
  it('takes the fields a snapshot carries', () => {
    const merged = mergeJobSnapshot(job(), snapshot({ state: 'verifying' }));
    expect(merged.state).toBe('verifying');
    expect(merged.currentStep).toBe('verify');
    expect(merged.updatedAt).toBe('2026-01-01T00:00:20Z');
  });

  it('keeps the fields a snapshot does not carry', () => {
    const merged = mergeJobSnapshot(job({ error: 'earlier failure' }), snapshot());
    expect(merged.command).toBe('offload');
    expect(merged.projectId).toBe('p1');
    expect(merged.error).toBe('earlier failure');
  });

  it('ignores a snapshot for a different job', () => {
    const original = job();
    expect(mergeJobSnapshot(original, snapshot({ id: 'other', state: 'failed' }))).toBe(original);
  });

  it('ignores a stale snapshot rather than rolling state backwards', () => {
    // A reconnect replay can deliver an old snapshot after a live event.
    const current = job({ state: 'succeeded', updatedAt: '2026-01-01T00:00:30Z' });
    const late = snapshot({ state: 'running', updatedAt: '2026-01-01T00:00:05Z' });
    expect(mergeJobSnapshot(current, late)).toBe(current);
  });

  it('applies a snapshot with an equal timestamp', () => {
    const current = job({ updatedAt: '2026-01-01T00:00:20Z', state: 'running' });
    expect(mergeJobSnapshot(current, snapshot({ state: 'verifying' })).state).toBe('verifying');
  });

  it('is a no-op for a null snapshot', () => {
    const original = job();
    expect(mergeJobSnapshot(original, null)).toBe(original);
  });
});

describe('snapshotProgress', () => {
  it('prefers bytes, the finest measure a transfer has', () => {
    // Steps would say 50% and items 25%; bytes are what actually moved.
    expect(
      snapshotProgress(
        snapshot({ completedItems: 1, totalItems: 4, bytesCopied: 300, totalBytes: 1000 }),
      ),
    ).toBe(0.3);
  });

  it('falls back to items when the runner cannot report bytes', () => {
    // A transcode has no usable output size, so it weights each file as one.
    expect(snapshotProgress(snapshot({ completedItems: 3, totalItems: 4 }))).toBe(0.75);
  });

  it('falls back to steps when there are no items at all', () => {
    expect(snapshotProgress(snapshot())).toBe(0.5);
  });

  it('is zero when nothing is measurable', () => {
    expect(snapshotProgress(snapshot({ totalSteps: 0 }))).toBe(0);
  });

  it('clamps every measure to the unit interval', () => {
    expect(snapshotProgress(snapshot({ bytesCopied: 900, totalBytes: 500 }))).toBe(1);
    expect(snapshotProgress(snapshot({ completedItems: 9, totalItems: 5 }))).toBe(1);
    expect(snapshotProgress(snapshot({ completedSteps: ['a', 'b', 'c'], totalSteps: 2 }))).toBe(1);
  });

  it('does not divide by a zero byte total for an empty-file job', () => {
    // Every entry is a zero-byte file: totalBytes is 0, so items must win
    // rather than the fraction becoming NaN.
    expect(snapshotProgress(snapshot({ completedItems: 2, totalItems: 4, totalBytes: 0 }))).toBe(
      0.5,
    );
  });
});

describe('progressLabel', () => {
  it('reports bytes when the runner knows them', () => {
    expect(progressLabel(snapshot({ bytesCopied: 1.5e9, totalBytes: 4e9 }))).toBe(
      '1.5 GB of 4.0 GB',
    );
  });

  it('reports files when it does not, with thousands separated', () => {
    expect(progressLabel(snapshot({ completedItems: 1200, totalItems: 3400 }))).toBe(
      '1,200 of 3,400 files',
    );
  });

  it('says nothing when the snapshot carries no counters', () => {
    expect(progressLabel(snapshot())).toBeNull();
  });
});

describe('liveProgress', () => {
  it('prefers the snapshot, which knows the real step count', () => {
    // The list-only fallback can only see *whether* a step is in flight, so
    // it reports one step's worth; the snapshot reports two of four.
    expect(liveProgress(job(), null)).toBe(0.25);
    expect(liveProgress(job(), snapshot())).toBe(0.5);
  });
});

describe('jobUpdatedFrame', () => {
  it('builds the same shape the live forward sends', () => {
    const frame = jobUpdatedFrame(snapshot());
    expect(frame.kind).toBe('event');
    expect(frame.method).toBe('job.updated');
    expect(frame.params.jobId).toBe('j1');
    expect(frame.params.snapshot.currentStep).toBe('verify');
  });
});

describe('assetFileName', () => {
  it('takes the last segment of a buried camera path', () => {
    expect(assetFileName('PRIVATE/M4ROOT/CLIP/C0001.MP4')).toBe('C0001.MP4');
  });

  it('handles a bare filename and a trailing slash', () => {
    expect(assetFileName('C0001.MP4')).toBe('C0001.MP4');
    expect(assetFileName('CLIP/C0001.MP4/')).toBe('C0001.MP4');
  });

  it('falls back to the input when there is nothing to take', () => {
    expect(assetFileName('')).toBe('');
    expect(assetFileName('/')).toBe('/');
  });

  it('is total: nullish input returns an empty name instead of throwing (#97)', () => {
    // A payload lacking sourceRelativePath used to reach the .split and
    // unmount the renderer tree; the name is rendered, never computed on.
    expect(assetFileName(null)).toBe('');
    expect(assetFileName(undefined)).toBe('');
  });
});

describe('isCompleteAsset', () => {
  it('accepts a payload that carries the fields the detail screen renders', () => {
    expect(isCompleteAsset(asset())).toBe(true);
  });

  it('rejects null and a payload without sourceRelativePath (#97)', () => {
    expect(isCompleteAsset(null)).toBe(false);
    // The fixture minus the one field the guard exists to check. The spread
    // keeps the payload shaped like the real thing rather than hand-built,
    // so the test fails if the guard starts checking a different field.
    const { sourceRelativePath: _omitted, ...partial } = asset();
    // SAFETY: `partial` is `Omit<AssetSummary, 'sourceRelativePath'>` stood
    // in for the unvalidated wire value a truncated payload delivers; the
    // assertion re-adds the declared type so it can be passed where the
    // compiled caller would have one, which is the situation under test.
    expect(isCompleteAsset(partial as AssetSummary)).toBe(false);
  });
});

describe('searchAssets', () => {
  const assets = [
    asset({ id: 'a', sourceRelativePath: 'CLIP/C0001.MP4', mediaKind: 'video' }),
    asset({ id: 'b', sourceRelativePath: 'AUDIO/take1.wav', mediaKind: 'audio' }),
  ];

  it('returns everything for an empty query', () => {
    expect(searchAssets(assets, '   ')).toHaveLength(2);
  });

  it('matches path, kind, and lifecycle state case-insensitively', () => {
    expect(searchAssets(assets, 'c0001').map((a) => a.id)).toEqual(['a']);
    expect(searchAssets(assets, 'AUDIO').map((a) => a.id)).toEqual(['b']);
    expect(searchAssets(assets, 'adopted')).toHaveLength(2);
  });

  it('tolerates a null media kind', () => {
    expect(searchAssets([asset({ mediaKind: null })], 'video')).toEqual([]);
  });
});

describe('sortAssets', () => {
  it('puts the newest first', () => {
    const rows = sortAssets([
      asset({ id: 'old', firstSeenAt: '2026-01-01T00:00:00Z' }),
      asset({ id: 'new', firstSeenAt: '2026-02-01T00:00:00Z' }),
    ]);
    expect(rows.map((a) => a.id)).toEqual(['new', 'old']);
  });

  it('breaks ties on path so the order is stable between renders', () => {
    const rows = sortAssets([
      asset({ id: 'b', sourceRelativePath: 'b.mov' }),
      asset({ id: 'a', sourceRelativePath: 'a.mov' }),
    ]);
    expect(rows.map((a) => a.id)).toEqual(['a', 'b']);
  });

  it('does not mutate its input', () => {
    const input = [
      asset({ id: 'old', firstSeenAt: '2026-01-01T00:00:00Z' }),
      asset({ id: 'new', firstSeenAt: '2026-02-01T00:00:00Z' }),
    ];
    sortAssets(input);
    expect(input.map((a) => a.id)).toEqual(['old', 'new']);
  });
});
