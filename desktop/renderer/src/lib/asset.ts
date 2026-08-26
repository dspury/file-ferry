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

/**
 * The availability note that goes under a replica's state chip, or null when
 * there is nothing left to add.
 *
 * A verified copy on an unmounted drive is still verified and still not
 * something you can open right now, which is the case this line exists for.
 * When availability *is* the state -- a missing replica -- the chip already
 * says "missing", and repeating it in lower case underneath read as a second,
 * weaker claim about the same fact.
 */
export function availabilityNote(r: ReplicaSummary): string | null {
  if (r.availability === 'online') return null;
  if (r.availability === replicaHealth(r)) return null;
  return r.availability;
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
 * The single message the whole tally collapses into.
 *
 * `terms` are `lifecycleState` values, not prose: `searchAssets` matches the
 * query against the path, the media kind and the lifecycle state, so the word
 * an operator types to list a group is the state the row is in. That is why
 * the unverified group is searched as `copied` and not as "unverified" -- the
 * screen's own word for it matches no row.
 */
export interface TallyNotice {
  /** Danger the moment anything is missing; a warning otherwise. */
  readonly tone: 'danger' | 'warn';
  readonly label: string;
  /** One phrase per non-zero group, in worst-first order. */
  readonly counts: readonly string[];
  /** The searchable state word for each counted group, same order. */
  readonly terms: readonly string[];
  /**
   * The instructions here that are about hardware rather than about the
   * table -- worst first, empty when no counted group implies one.
   *
   * These are the sentences that must survive the collapse whatever else
   * does: each one is the reason an operator should not release a card, and
   * each is tied to a different group, so a library that is both missing
   * assets and holding unverified copies gets both.
   */
  readonly safety: readonly string[];
}

const PLURAL = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/**
 * Collapse the lifecycle tally into one banner's worth of facts.
 *
 * Rendered one banner per non-clean tally, this block reached 193px -- 24% of
 * the fold at 1280x800 -- above a screen whose whole point is the table. Three
 * banners is also three severities to rank by eye when the ranking is already
 * known: missing outranks everything, so the block takes missing's severity
 * and states every count inside it.
 *
 * Nothing is dropped in the collapse. Every count, every search term and both
 * hardware instructions survive; what goes is the repetition of the frame
 * around them. Returns `null` for a clean library, which is what keeps the
 * block off the screen entirely rather than announcing that nothing is wrong.
 */
export function tallyNotice(tally: LifecycleTally): TallyNotice | null {
  const counts: string[] = [];
  const terms: string[] = [];
  // Worst first, so the count that decides the severity is also the count
  // read first.
  if (tally.missing > 0) {
    counts.push(`${PLURAL(tally.missing, 'asset', 'assets')} ferry can no longer find on disk`);
    terms.push('missing');
  }
  if (tally.needsReview > 0) {
    // "automatically" is load-bearing: a person still can, which is what
    // makes `needs_review` a queue to work through rather than a dead end.
    counts.push(
      `${PLURAL(tally.needsReview, 'asset', 'assets')} could not be classified automatically`,
    );
    terms.push('needs_review');
  }
  if (tally.unverified > 0) {
    counts.push(`${PLURAL(tally.unverified, 'asset', 'assets')} copied but not yet verified`);
    terms.push('copied');
  }
  if (counts.length === 0) return null;
  const safety: string[] = [];
  if (tally.missing > 0) {
    safety.push('Do not format or erase the source a missing asset came from.');
  }
  if (tally.unverified > 0) {
    safety.push('Until a copy is verified, the source is the only confirmed copy.');
  }
  return {
    tone: tally.missing > 0 ? 'danger' : 'warn',
    label: 'Needs attention',
    counts,
    terms,
    safety,
  };
}

/**
 * The part of a source path an operator actually scans for.
 *
 * Camera cards bury the file several directories deep
 * (`PRIVATE/M4ROOT/CLIP/C0012.MP4`), so a list keyed on the full relative
 * path is a column of near-identical prefixes. The name goes in the primary
 * column and the full path stays available beside it.
 *
 * Total on nullish input (#97): the wire is not validated in the renderer,
 * so a payload the type calls `AssetSummary` can still lack the field.
 * A throw here would blank the whole screen into the ErrorBoundary's
 * fallback -- recoverable now, but a name the function can render is
 * cheaper than a crash the operator has to retry past.
 */
export function assetFileName(relativePath: string | null | undefined): string {
  if (relativePath == null) return '';
  const segments = relativePath.split('/').filter((part) => part !== '');
  return segments[segments.length - 1] ?? relativePath;
}

/**
 * Whether a payload can be rendered by the asset detail screen (#97).
 *
 * The `sourceRelativePath` is the field the detail header is built from —
 * the page title and the path cell both `.split` it — so a response that
 * lacks it must take the not-found path rather than the render path.
 * The Python side makes this unreachable (the handler answers a missing
 * id with a typed error, and `AssetSummary` is a required-field model),
 * but a deep link is only ever one sidecar change away from a partial
 * payload, and the cost of checking is one comparison.
 */
export function isCompleteAsset(value: AssetSummary | null): value is AssetSummary {
  return value !== null && typeof value.sourceRelativePath === 'string';
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
