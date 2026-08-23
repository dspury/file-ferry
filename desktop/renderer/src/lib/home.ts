/**
 * Pure Home-screen logic (testable without React/DOM).
 *
 * The Home screen shows active jobs, connected sources, unsafe cards,
 * missing/unverified replicas, failed work, and proxy readiness. The
 * aggregation and health derivation live here so they are unit-testable.
 */
import type {
  JobDetail,
  AssetSummary,
  ReplicaSummary,
  DerivativeSummary,
} from '../../../shared/ipc-methods.js';

export interface HomeSummary {
  readonly activeJobs: number;
  readonly attentionJobs: number;
  readonly failedJobs: number;
  readonly unsafeCards: number;
  readonly unverifiedReplicas: number;
  readonly assets: number;
  readonly proxyPending: number;
}

const ACTIVE_STATES = new Set(['queued', 'running', 'verifying', 'resumable']);
const ATTENTION_STATES = new Set(['needs_attention', 'awaiting_review']);

/**
 * These three classifiers read nothing but `state`, so they ask for nothing
 * but `state`. A full `JobDetail` still satisfies the parameter, while a
 * caller holding only the state (the Home job chip) no longer has to
 * fabricate a whole job object to ask the question.
 */
export type JobStateOnly = Pick<JobDetail, 'state'>;

export function isJobActive(job: JobStateOnly): boolean {
  return ACTIVE_STATES.has(job.state);
}

export function isJobAttention(job: JobStateOnly): boolean {
  return ATTENTION_STATES.has(job.state);
}

export function isJobFailed(job: JobStateOnly): boolean {
  return job.state === 'failed';
}

/** A job with no successful proxy derivative is "proxy pending". */
export function proxyPending(
  jobs: readonly JobDetail[],
  derivativesByAsset: Map<string, readonly DerivativeSummary[]>,
): JobDetail[] {
  return jobs.filter((job) => {
    const derivatives = derivativesByAsset.get(job.projectId) ?? [];
    return !derivatives.some((d) => d.status === 'ready');
  });
}

export function summarizeHome(opts: {
  jobs: readonly JobDetail[];
  assets: readonly AssetSummary[];
  replicas: readonly ReplicaSummary[];
  proxyDerivatives: readonly DerivativeSummary[];
}): HomeSummary {
  const activeJobs = opts.jobs.filter(isJobActive).length;
  const attentionJobs = opts.jobs.filter(isJobAttention).length;
  const failedJobs = opts.jobs.filter(isJobFailed).length;
  const unverifiedReplicas = opts.replicas.filter((r) => !r.verified).length;
  // Proxy readiness is conservative: if any asset lacks a ready derivative,
  // report it pending.
  const readyProxyAssets = new Set(
    opts.proxyDerivatives.filter((d) => d.status === 'ready').map((d) => d.assetId),
  );
  const proxyPendingCount = opts.assets.filter((a) => !readyProxyAssets.has(a.id)).length;
  return {
    activeJobs,
    attentionJobs,
    failedJobs,
    unsafeCards: 0, // derived from intake sessions; filled by the screen when available
    unverifiedReplicas,
    assets: opts.assets.length,
    proxyPending: proxyPendingCount,
  };
}

/** A single Home status card model. */
export interface StatusCard {
  readonly label: string;
  readonly count: number;
  readonly tone: 'active' | 'ok' | 'warn' | 'danger' | 'attention' | 'neutral';
}

/**
 * The dashboard tiles.
 *
 * Active work is `active`, not `ok`. Running is not succeeded: green here
 * reported "1 active job" in the same colour the app uses for a verified
 * copy, so a card still mid-transfer read as a card safely landed -- and it
 * left the accent variant of the tile, which is what CinePrompt reserves for
 * live work, unused. The remaining tones are all "something is wrong to
 * degree N", which is the axis warn/danger/attention already covers.
 */
export function homeCards(s: HomeSummary): StatusCard[] {
  return [
    { label: 'Active jobs', count: s.activeJobs, tone: 'active' },
    { label: 'Needs attention', count: s.attentionJobs, tone: 'attention' },
    { label: 'Failed', count: s.failedJobs, tone: 'danger' },
    { label: 'Unsafe cards', count: s.unsafeCards, tone: 'danger' },
    { label: 'Unverified replicas', count: s.unverifiedReplicas, tone: 'warn' },
    { label: 'Proxy pending', count: s.proxyPending, tone: 'warn' },
  ];
}
