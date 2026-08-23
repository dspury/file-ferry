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
 * Overall health: danger if any required tool is missing, attention if
 * any optional integration (resolve) is absent, else ok. ffmpeg/ffprobe
 * are required; resolve is optional.
 */
export function overallHealth(doctor: DoctorResult): Health {
  const required = ['ffmpeg', 'ffprobe'];
  for (const tool of doctor.tools) {
    if (required.includes(tool.name) && !tool.present) {
      return 'danger';
    }
  }
  const resolve = doctor.tools.find((t) => t.name === 'resolve');
  if (resolve && !resolve.present) {
    return 'attention';
  }
  return 'ok';
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
  return name.toLowerCase().includes('resolve') ? 'attention' : 'danger';
}

/** Short human status for a tool. */
export function toolStatus(present: boolean): string {
  return present ? 'present' : 'missing';
}

/** Human-readable byte count. */

// Re-exported so existing callers keep importing it from here.
export { formatBytes } from './format.js';
