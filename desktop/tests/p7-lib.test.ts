/**
 * Tests for the pure Package 7b logic (settings validation + doctor
 * health derivation). These run in node without React/DOM.
 */
import { describe, expect, it } from 'vitest';
import { validateSettings, hasChanges, toUpdateParams } from '../renderer/src/lib/settings.js';
import { overallHealth, toolTone, toolStatus, formatBytes } from '../renderer/src/lib/doctor.js';
import type { AppSettings, DoctorResult, ToolCheck } from '../shared/ipc-methods.js';

function settings(over: Partial<AppSettings> = {}): AppSettings {
  return {
    proxyCodec: 'ProRes422Proxy',
    proxyHeight: 1080,
    checksumAlgo: 'xxhash64',
    resolvePath: null,
    ffmpegPath: null,
    organizeTemplate: '{root}/{source_relpath}/{filename}{ext}',
    organizeMode: 'copy',
    organizeOnConflict: 'skip',
    ...over,
  };
}

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

describe('validateSettings', () => {
  it('accepts a valid settings object', () => {
    const r = validateSettings(settings());
    expect(r.valid).toBe(true);
    expect(r.errors).toHaveLength(0);
  });

  it('rejects an unknown checksum algorithm', () => {
    const r = validateSettings(settings({ checksumAlgo: 'md5' }));
    expect(r.valid).toBe(false);
    expect(r.errors.join()).toContain('checksum');
  });

  it('rejects a non-positive proxy height', () => {
    expect(validateSettings(settings({ proxyHeight: 0 })).valid).toBe(false);
    expect(validateSettings(settings({ proxyHeight: -5 })).valid).toBe(false);
  });

  it('rejects an empty organize template', () => {
    expect(validateSettings(settings({ organizeTemplate: '  ' })).valid).toBe(false);
  });

  it('rejects an unknown mode', () => {
    expect(validateSettings(settings({ organizeMode: 'delete' })).valid).toBe(false);
  });
});

describe('toUpdateParams / hasChanges', () => {
  it('toUpdateParams carries every field', () => {
    const p = toUpdateParams(settings());
    expect(p.proxyCodec).toBe('ProRes422Proxy');
    expect(p.organizeMode).toBe('copy');
  });

  it('hasChanges detects a real change and ignores identity', () => {
    const base = settings();
    expect(hasChanges(settings(), base)).toBe(false);
    expect(hasChanges(settings({ proxyCodec: 'H264' }), base)).toBe(true);
  });
});

describe('doctor health', () => {
  it('danger when ffmpeg is missing', () => {
    const d = doctor([tool('ffmpeg', false), tool('ffprobe', true), tool('resolve', false)]);
    expect(overallHealth(d)).toBe('danger');
  });

  it('danger when ffprobe is missing', () => {
    const d = doctor([tool('ffmpeg', true), tool('ffprobe', false), tool('resolve', false)]);
    expect(overallHealth(d)).toBe('danger');
  });

  it('attention when only resolve is missing', () => {
    const d = doctor([tool('ffmpeg', true), tool('ffprobe', true), tool('resolve', false)]);
    expect(overallHealth(d)).toBe('attention');
  });

  it('ok when everything is present', () => {
    const d = doctor([tool('ffmpeg', true), tool('ffprobe', true), tool('resolve', true)]);
    expect(overallHealth(d)).toBe('ok');
  });

  it('toolTone: resolve missing is attention, others danger', () => {
    expect(toolTone('ffmpeg', false)).toBe('danger');
    expect(toolTone('resolve', false)).toBe('attention');
    expect(toolTone('ffmpeg', true)).toBe('ok');
  });

  it('toolStatus labels presence', () => {
    expect(toolStatus(true)).toBe('present');
    expect(toolStatus(false)).toBe('missing');
  });
});

describe('formatBytes', () => {
  it('formats bytes, MB, GB, TB', () => {
    expect(formatBytes(500)).toBe('500 B');
    expect(formatBytes(1.5e6)).toBe('1.5 MB');
    expect(formatBytes(2.5e9)).toBe('2.5 GB');
    expect(formatBytes(1.25e12)).toBe('1.3 TB');
  });
});
