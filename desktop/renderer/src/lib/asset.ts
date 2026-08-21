/**
 * Pure Asset/Clip-detail logic (testable without React/DOM).
 *
 * Derives replica health, logical clip grouping, and proxy readiness for
 * the Asset / Clip detail screen (plan §8.2).
 */
import type {
  AssetSummary,
  ReplicaSummary,
  DerivativeSummary,
  LogicalClip,
} from '../../../shared/ipc-methods.js';

export type ReplicaHealth = 'verified' | 'missing' | 'unverified';

export function replicaHealth(r: ReplicaSummary): ReplicaHealth {
  if (r.availability === 'missing') return 'missing';
  if (r.verified) return 'verified';
  return 'unverified';
}

export interface AssetOverview {
  readonly replicas: readonly ReplicaSummary[];
  readonly verifiedCount: number;
  readonly missingCount: number;
  readonly unverifiedCount: number;
  readonly derivatives: readonly DerivativeSummary[];
  readonly readyProxies: number;
  readonly clips: readonly LogicalClip[];
}

export function assetOverview(opts: {
  replicas: readonly ReplicaSummary[];
  derivatives: readonly DerivativeSummary[];
  clips: readonly LogicalClip[];
}): AssetOverview {
  const verifiedCount = opts.replicas.filter((r) => replicaHealth(r) === 'verified').length;
  const missingCount = opts.replicas.filter((r) => replicaHealth(r) === 'missing').length;
  const unverifiedCount = opts.replicas.filter((r) => replicaHealth(r) === 'unverified').length;
  const readyProxies = opts.derivatives.filter((d) => d.status === 'ready').length;
  return {
    replicas: opts.replicas,
    verifiedCount,
    missingCount,
    unverifiedCount,
    derivatives: opts.derivatives,
    readyProxies,
    clips: opts.clips,
  };
}

/** Proxy readiness label for an asset. */
export function proxyReadiness(overview: AssetOverview): 'ready' | 'pending' | 'none' {
  if (overview.readyProxies > 0) return 'ready';
  if (overview.derivatives.length > 0) return 'pending';
  return 'none';
}

/** True when a clip's members are all resolved (primary + sidecars present). */
export function clipResolved(clip: LogicalClip): boolean {
  return clip.resolved;
}

/** Find the clips an asset belongs to. */
export function clipsForAsset(clips: readonly LogicalClip[], assetId: string): LogicalClip[] {
  return clips.filter((c) => c.members.some((m) => m.assetId === assetId));
}

export function assetPath(asset: AssetSummary): string {
  return asset.sourceRelativePath;
}
