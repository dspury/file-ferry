/**
 * Tests for the pure logic changed by the #86 acceptance pass.
 *
 * Two of these guard a bug the pass found in production data rather than in
 * fixtures: `overallHealth` matched the optional integration by the exact
 * string `'resolve'`, but the sidecar reports "DaVinci Resolve", so the
 * Environment screen announced "Ready: 1 tool not found". Its allow-list of
 * required tools had the mirror-image problem — anything missing that was
 * neither ffmpeg nor ffprobe (the real doctor payload also carries `config`)
 * also fell through to `ok`.
 */
import { describe, expect, it } from 'vitest';
import {
  healthBanner,
  isOptionalTool,
  overallHealth,
  toolTone,
} from '../renderer/src/lib/doctor.js';
import { availabilityNote } from '../renderer/src/lib/asset.js';
import type { DoctorResult, ReplicaSummary, ToolCheck } from '../shared/ipc-methods.js';

function tool(name: string, present: boolean): ToolCheck {
  return { name, present, path: present ? `/bin/${name}` : null, message: null };
}

function doctor(tools: ToolCheck[]): DoctorResult {
  return {
    version: '0.0.0',
    protocolVersion: 1,
    tools,
    appDataDir: '/data',
    dbPath: '/data/db',
  };
}

function replica(availability: string, verified: boolean): ReplicaSummary {
  return {
    id: 1,
    assetId: 'ast_1',
    projectId: 'prj_1',
    path: '/Volumes/Work/A.mxf',
    checksum: verified ? 'abc123' : null,
    checksumAlgo: verified ? 'xxhash64' : null,
    verified,
    verifiedAt: verified ? '2026-08-14T18:03:00Z' : null,
    availability,
  };
}

describe('isOptionalTool', () => {
  it('matches the name the sidecar actually reports', () => {
    expect(isOptionalTool('DaVinci Resolve')).toBe(true);
    expect(isOptionalTool('resolve')).toBe(true);
  });

  it('does not match a tool ferry needs', () => {
    expect(isOptionalTool('ffmpeg')).toBe(false);
    expect(isOptionalTool('config')).toBe(false);
  });
});

describe('overallHealth', () => {
  it('is attention when the optional integration is reported by its real name', () => {
    const d = doctor([tool('ffmpeg', true), tool('ffprobe', true), tool('DaVinci Resolve', false)]);
    expect(overallHealth(d)).toBe('attention');
  });

  it('is danger for a missing tool that is not the optional one', () => {
    const d = doctor([tool('ffmpeg', true), tool('ffprobe', true), tool('config', false)]);
    expect(overallHealth(d)).toBe('danger');
  });

  it('is danger when a required tool is missing alongside the optional one', () => {
    const d = doctor([
      tool('ffmpeg', false),
      tool('ffprobe', true),
      tool('DaVinci Resolve', false),
    ]);
    expect(overallHealth(d)).toBe('danger');
  });

  it('never says ok while a tool is missing', () => {
    for (const name of ['ffmpeg', 'ffprobe', 'config', 'DaVinci Resolve', 'something-else']) {
      const d = doctor([tool(name, false)]);
      expect(overallHealth(d)).not.toBe('ok');
    }
  });
});

describe('healthBanner', () => {
  it('matches the tone its own chips use, per health tier', () => {
    expect(healthBanner('danger').tone).toBe('danger');
    expect(healthBanner('attention').tone).toBe('attention');
    expect(healthBanner('ok').tone).toBe('ok');
  });

  it('agrees with toolTone about the tool that decided the verdict', () => {
    const optional = doctor([tool('ffmpeg', true), tool('DaVinci Resolve', false)]);
    expect(healthBanner(overallHealth(optional)).tone).toBe(toolTone('DaVinci Resolve', false));

    const required = doctor([tool('ffmpeg', false), tool('DaVinci Resolve', true)]);
    expect(healthBanner(overallHealth(required)).tone).toBe(toolTone('ffmpeg', false));
  });

  it('names the severity in words, not only in hue', () => {
    expect(healthBanner('danger').label).toBe('Missing required');
    expect(healthBanner('attention').label).toBe('Incomplete');
    expect(healthBanner('ok').label).toBe('Ready');
  });
});

describe('availabilityNote', () => {
  it('says nothing about a replica that is simply online', () => {
    expect(availabilityNote(replica('online', true))).toBeNull();
  });

  it('reports an offline copy, which is the half the chip cannot say', () => {
    expect(availabilityNote(replica('offline', true))).toBe('offline');
  });

  it('does not repeat the state the chip already spells out', () => {
    expect(availabilityNote(replica('missing', false))).toBeNull();
  });
});
