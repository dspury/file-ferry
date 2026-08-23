/**
 * Pure Home-screen logic (testable without React/DOM).
 *
 * The Dashboard reports the state of the *work*: how much is in flight, how
 * much is waiting on a person, and how much failed. It deliberately reports
 * nothing else.
 *
 * It used to also carry unsafe-card, unverified-replica and proxy-readiness
 * counts. Those cannot be computed from where this screen stands: the IPC
 * surface exposes `replica.list` and `derivatives.list` per *asset*, so a
 * library-wide figure would be one call per asset, and there is no method at
 * all that lists intake sessions, which is what an unsafe card is. They were
 * therefore hard-coded to `0` and rendered as tiles anyway -- and `0` on a
 * tile called UNSAFE CARDS is not an absence, it is an assertion an operator
 * could format a card on. They are gone rather than faked; a library-wide
 * aggregate is a sidecar feature, and when one exists it will be shaped by
 * whatever method gets built rather than by the guess that used to live here.
 */
import type { JobDetail } from '../../../shared/ipc-methods.js';

export interface HomeSummary {
  readonly activeJobs: number;
  readonly attentionJobs: number;
  readonly failedJobs: number;
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

/**
 * A single Home status card model.
 *
 * The tone union is exactly what `homeCards` can emit, plus the `neutral`
 * the screen substitutes at a count of zero. `ok` and `warn` were in it for
 * the two tiles that are gone; a union member nothing can produce is the
 * same dead surface as a count nothing can compute.
 */
export interface StatusCard {
  readonly label: string;
  readonly count: number;
  readonly tone: 'active' | 'danger' | 'attention' | 'neutral';
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
  ];
}
