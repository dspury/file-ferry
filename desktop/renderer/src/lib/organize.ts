/**
 * Pure Organize-screen logic (testable without React/DOM).
 *
 * Existing-media adoption follows plan -> review -> execute -> verify ->
 * receipt (plan §4.3, §8.2). Organize never mutates on preview, and a
 * move requires explicit confirmation. These helpers gate the apply
 * action on real conditions, never optimistic state.
 */
import type {
  OrganizePreview,
  OrganizeOutcome,
  CollisionIssue,
  OrganizationProfile,
} from '../../../shared/ipc-methods.js';

export type OrganizeStage = 'source' | 'preview' | 'ready' | 'running' | 'done';

export function organizeStage(opts: {
  sourceEntries: number;
  preview: OrganizePreview | null;
  executing: boolean;
  done: boolean;
}): OrganizeStage {
  if (opts.done) return 'done';
  if (opts.executing) return 'running';
  if (opts.preview !== null) return 'ready';
  if (opts.sourceEntries > 0) return 'preview';
  return 'source';
}

/** A preview is applyable only when there are no collisions. */
export function previewApplyable(preview: OrganizePreview | null): boolean {
  if (preview === null) return false;
  return preview.collisions.length === 0;
}

/** Collisions block apply regardless of mode. */
export function collisionBlocks(preview: OrganizePreview | null): boolean {
  if (preview === null) return true;
  return preview.collisions.length > 0;
}

/** A move requires explicit confirmation (plan §4.3). */
export function moveRequiresConfirm(mode: 'copy' | 'move' | 'link', confirmMove: boolean): boolean {
  if (mode !== 'move') return false;
  return !confirmMove;
}

/** Summarize the apply outcome (no optimistic success: only real rows). */
/** Tally of an organize run, as shown in the Apply panel. */
export interface OrganizeOutcomeSummary {
  readonly ok: number;
  readonly failed: number;
  readonly total: number;
}

export function outcomeSummary(outcomes: readonly OrganizeOutcome[]): OrganizeOutcomeSummary {
  const ok = outcomes.filter((o) => o.ok).length;
  const failed = outcomes.filter((o) => !o.ok).length;
  return { ok, failed, total: outcomes.length };
}

/**
 * Banner severity for an apply outcome.
 *
 * A run where nothing landed is not a warning, it is a failure, and it used
 * to be dressed the same as a run that lost one file out of four hundred.
 * Any partial loss stays a warning: the successful writes are real and the
 * receipt names them, so red would overstate it.
 */
export function outcomeTone(summary: OrganizeOutcomeSummary): 'ok' | 'warn' | 'danger' {
  if (summary.failed === 0) return 'ok';
  if (summary.ok === 0) return 'danger';
  return 'warn';
}

/**
 * What the rail's last stage says, and in which tone.
 *
 * The rail stamped `DONE` in the accent the moment `organizeStage` reached
 * its terminal stage, which it does on *any* returned outcome -- so an apply
 * that wrote five of six entries put an accent DONE at the top of the page
 * while the sentence saying one file did not land sat 1053px down it. The
 * stage is the outcome, not the arrival, so it now reads the outcome's own
 * severity: the same `outcomeTone` the result banner uses, which keeps the
 * two from ever disagreeing.
 *
 * `Incomplete` rather than `Partial` because it is the word the banner
 * underneath already uses, and rather than `Failed` because five files did
 * land and the receipt names them -- calling that a failure would overstate
 * it in the opposite direction. `Failed` is kept for the run where nothing
 * landed at all, which is what `outcomeTone` calls `danger`.
 *
 * `accent` before an apply: the stage is then a *pending* one, and a pending
 * stage is drawn from its position in the rail, not from an outcome it does
 * not have yet.
 */
export interface ApplyStageMark {
  readonly label: string;
  readonly tone: 'accent' | 'warn' | 'danger';
}

export function applyStageMark(outcome: OrganizeOutcomeSummary | null): ApplyStageMark {
  if (outcome === null) return { label: 'Done', tone: 'accent' };
  switch (outcomeTone(outcome)) {
    case 'ok':
      return { label: 'Done', tone: 'accent' };
    case 'warn':
      return { label: 'Incomplete', tone: 'warn' };
    case 'danger':
      return { label: 'Failed', tone: 'danger' };
  }
}

/**
 * Which of the screen's actions is the next one, derived from the rail's
 * stage so the lit button and the lit stage cannot disagree. See
 * `ingestPrimary` for why only one action wears the filled accent.
 *
 * A satisfied action keeps its outline variant and stays pressable: a
 * preview never touches the filesystem, so re-previewing after changing the
 * profile or the mode is exactly what an operator should do.
 */
export type OrganizeAction = 'preview' | 'apply';

export function organizePrimary(stage: OrganizeStage): OrganizeAction {
  switch (stage) {
    case 'source':
    case 'preview':
      return 'preview';
    case 'ready':
    case 'running':
    case 'done':
      return 'apply';
  }
}

export function profileLabel(profile: OrganizationProfile): string {
  return `${profile.name} v${profile.version}`;
}

export function collisionCount(collisions: readonly CollisionIssue[]): number {
  return collisions.reduce((sum, c) => sum + c.count, 0);
}
