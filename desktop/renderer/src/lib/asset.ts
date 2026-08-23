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

/**
 * The tone for an asset's lifecycle state.
 *
 * These are the states the epic requires stay explicit, and until now every
 * one of them rendered as the same neutral grey plate -- `missing` included,
 * which is the single most consequential thing this screen can tell an
 * operator and read as unremarkable.
 *
 * `copied` is deliberately a warning rather than a success: bytes are on
 * disk but no checksum has confirmed them, so the source card is still the
 * only trustworthy copy. That distinction between `copied` and `verified` is
 * the whole reason the app exists, and drawing them in one colour would
 * erase it.
 */
export type LifecycleTone = 'neutral' | 'ok' | 'warn' | 'danger' | 'attention';

export function lifecycleTone(state: string): LifecycleTone {
  switch (state) {
    case 'verified':
      return 'ok';
    case 'copied':
      return 'warn';
    case 'needs_review':
      return 'attention';
    case 'missing':
    case 'quarantined':
      return 'danger';
    // `discovered` is seen on a source but not yet acted on: nothing has
    // happened and nothing is wrong. It is the state
    // `application/assets.py` writes on adoption, and the default any state
    // this build has not been taught falls back to.
    default:
      return 'neutral';
  }
}

/** How many assets sit in each state that needs a human. */
export interface LifecycleTally {
  readonly missing: number;
  readonly needsReview: number;
  readonly unverified: number;
}

/**
 * Count the states worth saying out loud above the table.
 *
 * A library of two hundred rows hides three MISSING chips somewhere in the
 * scroll. The tally is what makes them findable without reading every row,
 * and it is derived from the same `lifecycleState` the chips draw -- no new
 * data, no new request.
 */
export function lifecycleTally(assets: readonly AssetSummary[]): LifecycleTally {
  let missing = 0;
  let needsReview = 0;
  let unverified = 0;
  for (const asset of assets) {
    if (asset.lifecycleState === 'missing') missing += 1;
    else if (asset.lifecycleState === 'needs_review') needsReview += 1;
    else if (asset.lifecycleState === 'copied') unverified += 1;
  }
  return { missing, needsReview, unverified };
}

/**
 * The part of a source path an operator actually scans for.
 *
 * Camera cards bury the file several directories deep
 * (`PRIVATE/M4ROOT/CLIP/C0012.MP4`), so a list keyed on the full relative
 * path is a column of near-identical prefixes. The name goes in the primary
 * column and the full path stays available beside it.
 */
export function assetFileName(relativePath: string): string {
  const segments = relativePath.split('/').filter((part) => part !== '');
  return segments[segments.length - 1] ?? relativePath;
}

/** Case-insensitive search over the path, media kind, and lifecycle state. */
export function searchAssets(assets: readonly AssetSummary[], query: string): AssetSummary[] {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return [...assets];
  return assets.filter(
    (a) =>
      a.sourceRelativePath.toLowerCase().includes(q) ||
      (a.mediaKind ?? '').toLowerCase().includes(q) ||
      a.lifecycleState.toLowerCase().includes(q),
  );
}

/**
 * Newest first, ties broken by path so the order is stable.
 *
 * Without the tiebreak, two assets adopted in the same second could swap
 * places between renders and the row under the cursor would move.
 */
export function sortAssets(assets: readonly AssetSummary[]): AssetSummary[] {
  return [...assets].sort((a, b) => {
    if (a.firstSeenAt !== b.firstSeenAt) return a.firstSeenAt < b.firstSeenAt ? 1 : -1;
    return a.sourceRelativePath.localeCompare(b.sourceRelativePath);
  });
}
