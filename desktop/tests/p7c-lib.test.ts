/**
 * Tests for the pure Package 7c logic (Home, Projects, Asset detail).
 * These run in node without React/DOM.
 */
import { describe, expect, it } from 'vitest';
import {
  homeCards,
  isJobActive,
  isJobAttention,
  isJobFailed,
  summarizeHome,
} from '../renderer/src/lib/home.js';
import { policyHealth, policyLabel, projectRow } from '../renderer/src/lib/projects.js';
import {
  assetOverview,
  proxyReadiness,
  replicaHealth,
  clipsForAsset,
} from '../renderer/src/lib/asset.js';
import type {
  JobDetail,
  AssetSummary,
  ReplicaSummary,
  DerivativeSummary,
  LogicalClip,
  ProjectSummary,
  StoragePolicy,
} from '../shared/ipc-methods.js';

function job(id: string, state: string): JobDetail {
  return {
    id,
    projectId: 'proj-1',
    sessionId: null,
    command: 'copy',
    state,
    currentStep: null,
    totalSteps: 1,
    startedAt: null,
    updatedAt: '2026-08-12T17:30:00Z',
    finishedAt: null,
    error: null,
    resumable: state === 'resumable',
  };
}

function asset(id: string): AssetSummary {
  return {
    id,
    sourceId: 1,
    sourceRelativePath: `A/${id}.mov`,
    observedSize: 1000,
    observedMtime: 0,
    lifecycleState: 'adopted',
    mediaKind: 'video',
    firstSeenAt: '2026-08-12T17:30:00Z',
  };
}

function replica(id: number, verified: boolean, availability = 'present'): ReplicaSummary {
  return {
    id,
    assetId: 'asset-1',
    projectId: 'proj-1',
    path: `/vol/${id}.mov`,
    checksum: verified ? 'abc' : null,
    checksumAlgo: 'xxhash64',
    verified,
    verifiedAt: verified ? '2026-08-12T17:30:00Z' : null,
    availability,
  };
}

function derivative(id: number, status: string): DerivativeSummary {
  return {
    id,
    assetId: 'asset-1',
    kind: 'proxy',
    outputPath: `/proxies/${id}.mov`,
    settingsFingerprint: null,
    status,
    readiness: status === 'ready' ? 1 : 0.5,
  };
}

function policy(over: Partial<StoragePolicy> = {}): StoragePolicy {
  return {
    requiredReplicas: 2,
    backupOnDifferentVolume: true,
    checksumAlgo: 'xxhash64',
    safetyReserveBytes: 0,
    requireSourceFingerprint: true,
    ...over,
  };
}

function project(id: string, storagePolicy: StoragePolicy): ProjectSummary {
  return {
    id,
    name: `Project ${id}`,
    workingRoot: '/work',
    backupRoot: '/backup',
    status: 'active',
    storagePolicy,
    createdAt: '2026-08-12T17:30:00Z',
    updatedAt: '2026-08-12T17:30:00Z',
    archivedAt: null,
  };
}

describe('home', () => {
  it('classifies job states', () => {
    expect(isJobActive(job('a', 'running'))).toBe(true);
    expect(isJobActive(job('b', 'queued'))).toBe(true);
    expect(isJobActive(job('c', 'succeeded'))).toBe(false);
    expect(isJobAttention(job('d', 'needs_attention'))).toBe(true);
    expect(isJobFailed(job('e', 'failed'))).toBe(true);
  });

  it('summarizes counts', () => {
    const s = summarizeHome({
      jobs: [
        job('a', 'running'),
        job('b', 'needs_attention'),
        job('c', 'failed'),
        job('d', 'succeeded'),
      ],
      assets: [asset('asset-1'), asset('asset-2')],
      replicas: [replica(1, true), replica(2, false)],
      proxyDerivatives: [derivative(1, 'ready')],
    });
    expect(s.activeJobs).toBe(1);
    expect(s.attentionJobs).toBe(1);
    expect(s.failedJobs).toBe(1);
    expect(s.unverifiedReplicas).toBe(1);
    expect(s.assets).toBe(2);
    // asset-1 has a ready derivative; asset-2 lacks one -> proxy pending.
    expect(s.proxyPending).toBe(1);
  });

  it('builds status cards', () => {
    const cards = homeCards({
      activeJobs: 2,
      attentionJobs: 1,
      failedJobs: 0,
      unsafeCards: 1,
      unverifiedReplicas: 0,
      assets: 5,
      proxyPending: 3,
    });
    expect(cards.find((c) => c.label === 'Failed')?.tone).toBe('danger');
    // `active`, not `ok`: running is not succeeded, and the success tone on
    // this tile made a card still mid-transfer read as a card safely landed.
    expect(cards.find((c) => c.label === 'Active jobs')?.tone).toBe('active');
  });
});

describe('projects', () => {
  it('policyHealth: ok when replicas verified meet the requirement', () => {
    const p = project('p1', policy());
    expect(policyHealth(p, 2)).toBe('ok');
  });

  it('policyHealth: danger when backup required but missing', () => {
    const p: ProjectSummary = { ...project('p1', policy()), backupRoot: null };
    expect(policyHealth(p, 2)).toBe('danger');
  });

  it('policyHealth: warn when replicas fall short', () => {
    expect(policyHealth(project('p1', policy()), 1)).toBe('warn');
  });

  it('policyLabel summarizes the policy', () => {
    expect(policyLabel(policy())).toContain('2 replica(s)');
    expect(policyLabel(policy())).toContain('xxhash64');
  });

  it('projectRow aggregates', () => {
    const row = projectRow(
      project('p1', policy()),
      [asset('1'), asset('2')],
      [replica(1, true), replica(2, false)],
      [derivative(1, 'ready')],
    );
    expect(row.assets).toBe(2);
    expect(row.verifiedReplicas).toBe(1);
    expect(row.readyDerivatives).toBe(1);
    expect(row.health).toBe('warn');
  });
});

describe('asset detail', () => {
  it('replicaHealth classifies', () => {
    expect(replicaHealth(replica(1, true))).toBe('verified');
    expect(replicaHealth(replica(2, false))).toBe('unverified');
    expect(replicaHealth({ ...replica(3, false), availability: 'missing' })).toBe('missing');
  });

  it('assetOverview counts replicas and proxies', () => {
    const o = assetOverview({
      replicas: [
        replica(1, true),
        replica(2, false),
        { ...replica(3, false), availability: 'missing' },
      ],
      derivatives: [derivative(1, 'ready'), derivative(2, 'pending')],
      clips: [],
    });
    expect(o.verifiedCount).toBe(1);
    expect(o.unverifiedCount).toBe(1);
    expect(o.missingCount).toBe(1);
    expect(o.readyProxies).toBe(1);
    expect(proxyReadiness(o)).toBe('ready');
  });

  it('proxyReadiness: pending when derivatives exist but none ready', () => {
    const o = assetOverview({ replicas: [], derivatives: [derivative(1, 'running')], clips: [] });
    expect(proxyReadiness(o)).toBe('pending');
  });

  it('clipsForAsset filters membership', () => {
    const clip: LogicalClip = {
      id: 1,
      sourceId: 1,
      clipName: 'SCENE_01',
      confidence: 1,
      resolved: true,
      members: [{ assetId: 'asset-1', role: 'primary' }],
    };
    expect(clipsForAsset([clip], 'asset-1')).toHaveLength(1);
    expect(clipsForAsset([clip], 'other')).toHaveLength(0);
  });
});
