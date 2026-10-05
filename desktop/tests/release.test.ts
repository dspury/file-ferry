/**
 * Tests for release provenance (plan §10 Pkg9 step 2) and for the packaging
 * wiring that guards a packaged build.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { getReleaseInfo, releaseSummary, __setReleaseInfo } from '../shared/release.js';
import { PROTOCOL_VERSION } from '../shared/version.js';

const DESKTOP = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(DESKTOP, '..');

function desktopScripts(): Record<string, string> {
  // SAFETY: package.json is a checked-in file in this repo and its `scripts`
  // block is a flat string map; the cast names that shape rather than leaving
  // every caller to re-narrow it.
  const pkg = JSON.parse(readFileSync(resolve(DESKTOP, 'package.json'), 'utf8')) as {
    scripts: Record<string, string>;
  };
  return pkg.scripts;
}
describe('release provenance', () => {
  it('defaults to a dev stamp with the frozen protocol version', () => {
    const info = getReleaseInfo();
    expect(info.protocolVersion).toBe(PROTOCOL_VERSION);
    expect(info.version).toBeTypeOf('string');
    expect(info.commit).toBeTypeOf('string');
  });

  it('supports a stamped override for packaged builds', () => {
    __setReleaseInfo({
      version: '0.3.0',
      commit: 'abc1234',
      buildTime: '2026-08-14T12:00:00Z',
      arch: 'arm64',
      protocolVersion: PROTOCOL_VERSION,
    });
    const info = getReleaseInfo();
    expect(info.version).toBe('0.3.0');
    expect(info.commit).toBe('abc1234');
    expect(info.arch).toBe('arm64');
    expect(info.protocolVersion).toBe(PROTOCOL_VERSION);
  });

  it('releaseSummary renders a diagnostic-ready block', () => {
    const summary = releaseSummary({
      version: '0.3.0',
      commit: 'abc1234',
      buildTime: '2026-08-14T12:00:00Z',
      arch: 'arm64',
      protocolVersion: 1,
    });
    expect(summary).toContain('version=0.3.0');
    expect(summary).toContain('commit=abc1234');
    expect(summary).toContain('arch=arm64');
    expect(summary).toContain('protocol=1');
  });
});

describe('packaging wiring', () => {
  const scripts = desktopScripts();

  it('runs the sidecar guard before every packaging path', () => {
    // The guard has to sit between freezing the sidecar and handing off to
    // electron-builder. After `build:sidecar` catches a sidecar that was never
    // built at all; before electron-builder, which would not notice.
    for (const name of ['package:mac', 'package:mac:local']) {
      const script = scripts[name] ?? '';
      expect(script, `${name} is missing from package.json`).not.toBe('');
      expect(script, `${name} does not run the guard`).toContain('check-sidecars.ts');
      expect(script.indexOf('check-sidecars.ts')).toBeGreaterThan(script.indexOf('build:sidecar'));
      expect(script.indexOf('check-sidecars.ts')).toBeLessThan(
        script.indexOf('electron-builder') === -1
          ? script.length
          : script.indexOf('electron-builder'),
      );
    }
  });

  it('the release script runs the guard too', () => {
    const release = readFileSync(resolve(REPO, 'scripts', 'package-release.sh'), 'utf8');
    expect(release).toContain('check-sidecars.ts');
  });

  it('every path named by the guard actually exists', () => {
    // Renaming the guard once left `package:mac` and `package-release.sh`
    // pointing at a file that no longer existed, so packaging would have
    // failed with a bare module-not-found instead of a diagnosis.
    expect(existsSync(resolve(DESKTOP, 'scripts', 'check-sidecars.ts'))).toBe(true);
  });

  it('threads ARCH into the sidecar build rather than defaulting to the host', () => {
    // `bash build-sidecar.sh` with no argument freezes `$(uname -m)`, so
    // ARCH=x64 would stamp an x64 release and ship an arm64 sidecar.
    expect(scripts['build:sidecar'] ?? '').toContain('${ARCH:-}');
  });
});
