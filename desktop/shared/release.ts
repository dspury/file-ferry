/**
 * Release provenance (plan §10 Pkg9 step 2).
 *
 * Every packaged build carries a reproducible source stamp so a reviewer
 * can identify exactly what shipped. The stamp is filled at build time
 * by the release script (see scripts/package-release.sh); the runtime
 * surfaces it via app.diagnostics so a diagnostic report identifies the
 * exact build.
 */
import { PROTOCOL_VERSION } from './version.js';

export interface ReleaseInfo {
  /** Semantic version from package.json. */
  readonly version: string;
  /** Short git commit SHA the build came from, or "unknown". */
  readonly commit: string;
  /** Build timestamp (ISO). */
  readonly buildTime: string;
  /** Target arch (arm64/x64). */
  readonly arch: string;
  /** Frozen protocol version. */
  readonly protocolVersion: number;
}

const DEFAULTS: ReleaseInfo = {
  version: '0.0.0-dev',
  commit: 'unknown',
  buildTime: new Date(0).toISOString(),
  arch: '',
  protocolVersion: PROTOCOL_VERSION,
};

let override: ReleaseInfo | null = null;

/** Inject release provenance (called by the release script / tests). */
export function __setReleaseInfo(info: ReleaseInfo): void {
  override = info;
}

/** Read the current release provenance (dev builds use defaults). */
export function getReleaseInfo(): ReleaseInfo {
  if (override) return override;
  return { ...DEFAULTS };
}

/** Format a provenance line for the diagnostic report. */
export function releaseSummary(info: ReleaseInfo): string {
  return `version=${info.version}\ncommit=${info.commit}\nbuildTime=${info.buildTime}\narch=${info.arch}\nprotocol=${info.protocolVersion}`;
}
