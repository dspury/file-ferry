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

/** Per-tool tone: missing required tools are danger, optional are attention. */
export function toolTone(name: string, present: boolean): 'ok' | 'danger' | 'attention' {
  if (present) return 'ok';
  return name === 'resolve' ? 'attention' : 'danger';
}

/** Short human status for a tool. */
export function toolStatus(present: boolean): string {
  return present ? 'present' : 'missing';
}

/** Human-readable byte count. */
export function formatBytes(n: number): string {
  if (n >= 1e12) return `${(n / 1e12).toFixed(1)} TB`;
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${n} B`;
}
