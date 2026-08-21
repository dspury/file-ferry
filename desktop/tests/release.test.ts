/**
 * Tests for release provenance (plan §10 Pkg9 step 2).
 */
import { describe, expect, it } from 'vitest';
import { getReleaseInfo, releaseSummary, __setReleaseInfo } from '../shared/release.js';
import { PROTOCOL_VERSION } from '../shared/version.js';

describe('release provenance', () => {
  it('defaults to a dev stamp with the frozen protocol version', () => {
    const info = getReleaseInfo();
    expect(info.protocolVersion).toBe(PROTOCOL_VERSION);
    expect(typeof info.version).toBe('string');
    expect(typeof info.commit).toBe('string');
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
