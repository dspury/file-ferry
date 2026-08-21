/**
 * Local diagnostics helpers (pure).
 *
 * Electron main owns diagnostic logs and a "open diagnostic folder"
 * affordance (ADR-0001, plan §8.1). The path-derivation and report
 * shaping here are pure so they are testable without Electron; the
 * Electron-specific open/append handlers live in `electron/diagnostics.ts`.
 */

export interface DiagnosticReport {
  readonly platform: string;
  readonly electronVersion: string;
  readonly protocolVersion: number;
  readonly sidecarStatus: string;
  readonly dbPath: string;
  readonly appDataDir: string;
  readonly logDir: string;
  readonly logCount: number;
}

/** Derive the diagnostic log directory name under an app-data dir. */
export function logDirectoryName(): string {
  return 'logs';
}

/**
 * Shape a human-readable diagnostics line. Fields are kept conservative:
 * the renderer must never receive unbounded FFmpeg output or arbitrary
 * filesystem content (plan §8.3), so the report is a short summary.
 */
export function formatDiagnosticSummary(report: DiagnosticReport): string {
  return [
    `platform=${report.platform}`,
    `electron=${report.electronVersion}`,
    `protocol=${report.protocolVersion}`,
    `sidecar=${report.sidecarStatus}`,
    `db=${report.dbPath}`,
    `appData=${report.appDataDir}`,
    `logDir=${report.logDir}`,
    `logCount=${report.logCount}`,
  ].join('\n');
}
