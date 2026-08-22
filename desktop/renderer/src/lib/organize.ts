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

export function profileLabel(profile: OrganizationProfile): string {
  return `${profile.name} v${profile.version}`;
}

export function collisionCount(collisions: readonly CollisionIssue[]): number {
  return collisions.reduce((sum, c) => sum + c.count, 0);
}
