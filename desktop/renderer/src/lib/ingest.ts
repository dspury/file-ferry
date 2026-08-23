/**
 * Pure Ingest-screen logic (testable without React/DOM).
 *
 * The Ingest flow is plan -> review -> execute -> verify -> receipt
 * (plan §4.2, §8.2). The screen must NOT show optimistic success; these
 * helpers gate each stage on real data.
 */
import { formatBytes } from './format.js';
import type {
  IntakePlan,
  PlanDestination,
  SourceInspectResult,
} from '../../../shared/ipc-methods.js';

export interface IngestStage {
  readonly stage: 'source' | 'destinations' | 'plan' | 'ready' | 'running' | 'done';
}

/** A reviewable plan requires destinations and a non-empty entry list. */
export function planReviewable(plan: IntakePlan | null): boolean {
  if (plan === null) return false;
  if (plan.destinations.length === 0) return false;
  if (plan.entries.length === 0) return false;
  return true;
}

/** True when the plan has a capacity problem that blocks execution. */
export function planBlocked(plan: IntakePlan | null): boolean {
  if (plan === null) return true;
  return !plan.capacityOk;
}

/** A source is ready to plan once inspected with entries. */
export function sourceReady(source: SourceInspectResult | null): boolean {
  if (source === null) return false;
  return source.entries.length > 0;
}

/** Human capacity note from a plan. */
export function capacityLabel(plan: IntakePlan): string {
  return plan.capacityOk ? 'capacity ok' : `needs ${formatBytes(plan.neededBytes)} more`;
}

/** Distinct destination kinds in a plan. */
export function destinationKinds(destinations: readonly PlanDestination[]): string[] {
  return [...new Set(destinations.map((d) => d.kind))];
}

/** The stage label shown to the user, gating on real data. */
export function ingestStage(opts: {
  source: SourceInspectResult | null;
  plan: IntakePlan | null;
  executing: boolean;
  done: boolean;
}): IngestStage['stage'] {
  if (opts.done) return 'done';
  if (opts.executing) return 'running';
  if (planReviewable(opts.plan)) return 'ready';
  if (sourceReady(opts.source)) return 'plan';
  if (opts.source !== null) return 'destinations';
  return 'source';
}

/**
 * Which of the screen's actions is the *next* one.
 *
 * Every stage's action stayed a filled accent primary once it had been used,
 * so the plan stage showed `Scan source` and `Build plan` as two solid accent
 * slabs at once, under an accent-filled active stage marker. The reskin
 * reserves that fill for "this is the thing to press", and three of them is
 * none of them.
 *
 * The answer is derived from the rail's own stage rather than from a second
 * notion of "current", so the lit button and the lit stage cannot disagree:
 * exactly one action is the primary at any stage, every other action keeps
 * its outline variant, and none of them is disabled by this -- re-scanning a
 * source or rebuilding a plan is legitimate and costs nothing but a read.
 *
 * `destinations` is a source that inspected to zero entries: the plan is
 * still what comes next there, and `Build plan` is the button that says so.
 */
export type IngestAction = 'scan' | 'plan' | 'execute' | 'watch';

export function ingestPrimary(stage: IngestStage['stage']): IngestAction {
  switch (stage) {
    case 'source':
      return 'scan';
    case 'destinations':
    case 'plan':
      return 'plan';
    case 'ready':
    case 'running':
      return 'execute';
    case 'done':
      // Nothing further happens on this screen once the job exists; the
      // verification an operator is waiting on happens in Activity.
      return 'watch';
  }
}

// Re-exported so existing callers keep importing it from here.
export { formatBytes };
