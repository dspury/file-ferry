/**
 * Pure diagnostic report logic (testable without React/DOM).
 *
 * app.diagnostics returns a single summary string (see
 * electron/diagnostics.ts + shared/diagnostics.ts). This module shapes
 * it into a copyable report and drives clipboard/export decisions.
 */

export interface DiagnosticReport {
  readonly summary: string;
  readonly generatedAt: string;
  readonly appVersion: string;
}

/** Build the full diagnostic report text from the summary. */
export function buildReportText(report: DiagnosticReport): string {
  const header = [
    `ferry diagnostic report`,
    `generated at: ${report.generatedAt}`,
    `app version: ${report.appVersion}`,
    '',
  ].join('\n');
  return header + report.summary + '\n';
}

/** The clipboard is usable when a report is non-empty. */
export function canCopy(report: DiagnosticReport | null): boolean {
  if (report === null) return false;
  return report.summary.trim().length > 0;
}

/** Suggested file name for an exported diagnostic report. */
export function diagnosticFileName(stamp: string, ext = 'txt'): string {
  const safe = stamp.replace(/[^0-9]/g, '').slice(0, 14) || 'unknown';
  return `ferry-diagnostics-${safe}.${ext}`;
}
