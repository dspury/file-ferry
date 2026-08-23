/**
 * Pure doctor/onboarding logic (testable without React/DOM).
 *
 * Derives the overall environment health and per-tool tone from the
 * DoctorResult so the Onboarding screen's safety semantics are
 * unit-testable.
 */
import type { DoctorResult } from '../../../shared/ipc-methods.js';

export type Health = 'ok' | 'attention' | 'danger';

/**
 * The one optional dependency.
 *
 * Matched case-insensitively on a substring because the sidecar reports the
 * tool as the operator knows it -- "DaVinci Resolve" -- and this predicate is
 * shared with {@link toolTone} on purpose: the two derivations testing the
 * name separately is what let the banner and the chip disagree about the same
 * tool in the first place, and a second copy of the test would let them drift
 * apart again.
 */
export function isOptionalTool(name: string): boolean {
  return name.toLowerCase().includes('resolve');
}

/**
 * Overall health: danger if anything ferry actually needs is missing,
 * attention if only the optional Resolve integration is, else ok.
 *
 * Required is defined by exclusion rather than by an allow-list of
 * `['ffmpeg', 'ffprobe']`. A tool the sidecar reports and cannot find is a
 * tool ferry wanted; with an allow-list, any other absence -- `config` is in
 * the real doctor payload -- fell through to `ok`, so the screen could
 * announce "Ready: 1 tool not found".
 */
export function overallHealth(doctor: DoctorResult): Health {
  const missing = doctor.tools.filter((t) => !t.present);
  if (missing.length === 0) return 'ok';
  if (missing.some((t) => !isOptionalTool(t.name))) return 'danger';
  return 'attention';
}

/**
 * Per-tool tone: missing required tools are danger, optional are attention.
 *
 * The name match is a case-insensitive substring because the sidecar reports
 * the tool as the operator knows it -- "DaVinci Resolve" -- and an exact
 * `=== 'resolve'` test therefore never fired. The result was a missing
 * optional integration drawn in danger red directly under a banner calling
 * the same fact merely "Incomplete": two different severities for one
 * condition, on one screen.
 */
export function toolTone(name: string, present: boolean): 'ok' | 'danger' | 'attention' {
  if (present) return 'ok';
  return isOptionalTool(name) ? 'attention' : 'danger';
}

/** The verdict banner's tone and the word it stamps on the message. */
export interface HealthVerdict {
  readonly tone: 'ok' | 'danger' | 'attention';
  readonly label: string;
}

/**
 * The verdict banner's severity, derived from the same `overallHealth` the
 * per-tool chips are derived from.
 *
 * The screen used to hard-code `warn` for any absence at all, and never
 * called `overallHealth` — so a missing *required* tool was announced as
 * merely "Incomplete" in warning yellow directly above its own chip in
 * danger red, and the optional case put a warn-yellow banner over an
 * attention-purple chip. One fact, two severities, twice.
 */
export function healthBanner(health: Health): HealthVerdict {
  if (health === 'danger') return { tone: 'danger', label: 'Missing required' };
  if (health === 'attention') return { tone: 'attention', label: 'Incomplete' };
  return { tone: 'ok', label: 'Ready' };
}

/** Short human status for a tool. */
export function toolStatus(present: boolean): string {
  return present ? 'present' : 'missing';
}

/** Human-readable byte count. */

// Re-exported so existing callers keep importing it from here.
export { formatBytes } from './format.js';
