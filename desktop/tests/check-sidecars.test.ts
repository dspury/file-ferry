/**
 * Tests for the packaged-sidecar guard (scripts/check-sidecars.ts).
 *
 * The defect this guards is one that produced a real artifact: electron-builder
 * does not fail on a missing `sidecar/${arch}`, it exits 0 and ships a
 * `ferry.app` with no sidecar in it, which dies on launch. Reproduced against
 * the real config on 2026-10-05.
 *
 * These tests run entirely against in-memory fixtures — the `readFile` and
 * `fileExists` seams are injected — so none of them can be satisfied by a
 * stale build tree, and none of them touch the real `desktop/sidecar/`.
 */

import { describe, expect, it } from 'vitest';
import {
  checkSidecars,
  declaredTargets,
  normaliseArch,
  readMachOArchitectures,
  type SidecarEnvironment,
} from '../scripts/check-sidecars.ts';

const CPU_X86_64 = 0x01000007;
const CPU_ARM64 = 0x0100000c;
const MACH_MAGIC_64 = 0xfeedfacf;
const FAT_MAGIC = 0xcafebabe;

/** A thin 64-bit Mach-O header naming one CPU type. */
function thinMachO(cpu: number): Buffer {
  const buf = Buffer.alloc(32);
  buf.writeUInt32LE(MACH_MAGIC_64, 0);
  buf.writeUInt32LE(cpu, 4);
  return buf;
}

/** A fat (universal) header naming several CPU types. */
function fatMachO(...cpus: number[]): Buffer {
  const buf = Buffer.alloc(8 + cpus.length * 20);
  buf.writeUInt32BE(FAT_MAGIC, 0);
  buf.writeUInt32BE(cpus.length, 4);
  cpus.forEach((cpu, i) => buf.writeUInt32BE(cpu, 8 + i * 20));
  return buf;
}

/**
 * A file in the fake tree. Text and binary are separate variants so each
 * reader can hand back the representation its contract promises, rather than
 * the fixture asserting a union into the right shape.
 */
type FixtureFile =
  | {
      readonly kind: 'text';
      readonly text: string;
      readonly executable?: boolean;
      readonly isFile?: boolean;
    }
  | {
      readonly kind: 'binary';
      readonly binary: Buffer;
      readonly executable?: boolean;
      readonly isFile?: boolean;
    };

/**
 * Build `readFile` / `fileExists` seams over a path -> file map. Anything not
 * in the map does not exist, which is the case that matters most here.
 */
function fixture(files: Record<string, FixtureFile>, config: string) {
  const lookup = (path: string): FixtureFile => {
    const file = files[path];
    if (!file) throw new Error(`ENOENT: ${path}`);
    return file;
  };
  const readText = (path: string): string => {
    if (path === '/config.yml') return config;
    const file = lookup(path);
    return file.kind === 'text' ? file.text : file.binary.toString('binary');
  };
  const readBinary = (path: string): Buffer => {
    const file = lookup(path);
    return file.kind === 'text' ? Buffer.from(file.text, 'utf8') : file.binary;
  };
  const fileExists = (path: string) => {
    if (path === '/config.yml') return { isFile: () => true, mode: 0o644 };
    const file = files[path];
    if (!file) return null;
    return {
      isFile: () => file.isFile ?? true,
      mode: file.executable === false ? 0o644 : 0o755,
    };
  };
  return { readText, readBinary, fileExists };
}

function run(
  config: string,
  files: Record<string, FixtureFile>,
  overrides: Partial<SidecarEnvironment> = {},
) {
  return checkSidecars({
    configPath: '/config.yml',
    sidecarRoot: '/sidecar',
    hostPlatform: 'darwin',
    ...fixture(files, config),
    ...overrides,
  });
}

const TWO_ARCH_CONFIG = `
mac:
  target:
    - target: dmg
      arch:
        - arm64
        - x64
`;

describe('normaliseArch', () => {
  it('collapses every spelling electron-builder and uname use', () => {
    expect(normaliseArch('x64')).toBe('x64');
    expect(normaliseArch('x86_64')).toBe('x64');
    expect(normaliseArch('amd64')).toBe('x64');
    expect(normaliseArch('arm64')).toBe('arm64');
    expect(normaliseArch('aarch64')).toBe('arm64');
    expect(normaliseArch('ARM64')).toBe('arm64');
  });

  it('passes an unrecognised arch through rather than guessing', () => {
    expect(normaliseArch('mips')).toBe('mips');
  });
});

describe('readMachOArchitectures', () => {
  it('reads a thin arm64 binary', () => {
    expect([...readMachOArchitectures(thinMachO(CPU_ARM64))]).toEqual(['arm64']);
  });

  it('reads a thin x86_64 binary', () => {
    expect([...readMachOArchitectures(thinMachO(CPU_X86_64))]).toEqual(['x64']);
  });

  it('reads a universal binary as satisfying every slice it contains', () => {
    const archs = readMachOArchitectures(fatMachO(CPU_ARM64, CPU_X86_64));
    expect([...archs].sort()).toEqual(['arm64', 'x64']);
  });

  it('throws rather than returning an empty set on a non-Mach-O file', () => {
    // A truncated freeze, or a wrapper script left where the binary should be.
    // An empty set would read as "no match" by accident; it must be an error.
    expect(() => readMachOArchitectures(Buffer.from('#!/bin/sh\necho hi\n'))).toThrow(
      /not a Mach-O binary/,
    );
  });

  it('throws on a file too short to hold a header', () => {
    expect(() => readMachOArchitectures(Buffer.alloc(4))).toThrow(/too short/);
  });

  it('throws on a fat binary whose header is truncated', () => {
    const truncated = Buffer.alloc(20);
    truncated.writeUInt32BE(FAT_MAGIC, 0);
    truncated.writeUInt32BE(4, 4); // claims four slices, supplies none
    expect(() => readMachOArchitectures(truncated)).toThrow(/truncated/);
  });
});

describe('declaredTargets', () => {
  it('expands a target list into one entry per arch', () => {
    const { targets } = declaredTargets({
      mac: { target: [{ target: 'dmg', arch: ['arm64', 'x64'] }] },
    });
    expect(targets).toEqual([
      { platform: 'mac', arch: 'arm64', target: 'dmg' },
      { platform: 'mac', arch: 'x64', target: 'dmg' },
    ]);
  });

  it('normalises the arch names it reads out of the config', () => {
    const { targets } = declaredTargets({
      mac: { target: [{ target: 'dmg', arch: ['aarch64', 'x86_64'] }] },
    });
    expect(targets.map((t) => t.arch)).toEqual(['arm64', 'x64']);
  });

  it('flags a target that declares no arch instead of assuming one', () => {
    // electron-builder would substitute its own default. That ambiguity is how
    // a bundle gets built for an arch nobody froze a sidecar for.
    const { targets, problems } = declaredTargets({ mac: { target: [{ target: 'dmg' }] } });
    expect(targets).toEqual([]);
    expect(problems).toHaveLength(1);
    expect(problems[0]?.kind).toBe('implicit-arch');
  });

  it('accepts the shorthand string form of target', () => {
    const { targets, problems } = declaredTargets({ linux: { target: 'AppImage', arch: 'x64' } });
    expect(targets).toEqual([{ platform: 'linux', arch: 'x64', target: 'AppImage' }]);
    expect(problems).toEqual([]);
  });
});

describe('checkSidecars', () => {
  const bothPresent = {
    '/sidecar/arm64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
    '/sidecar/x64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_X86_64) },
  };

  it('passes when every declared arch has a matching sidecar', () => {
    const result = run(TWO_ARCH_CONFIG, bothPresent);
    expect(result.ok).toBe(true);
    expect(result.problems).toEqual([]);
    expect(result.checked.map((c) => c.arch)).toEqual(['arm64', 'x64']);
  });

  it('fails when one declared arch has no sidecar — the defect that shipped', () => {
    // Only arm64 was ever frozen. This is the real state of the repo until
    // x64 is built or dropped, and it is the case that produced an x64 .app
    // with no Contents/Resources/sidecar/ and a build exit code of 0.
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
    });
    expect(result.ok).toBe(false);
    expect(result.problems).toHaveLength(1);
    expect(result.problems[0]?.kind).toBe('missing');
    expect(result.problems[0]?.message).toContain('mac/x64');
    // The arm64 target is still reported as checked, so the failure names one
    // gap rather than implying the whole build is broken.
    expect(result.checked.map((c) => c.arch)).toEqual(['arm64']);
  });

  it('tells you the command that fixes the gap', () => {
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
    });
    expect(result.problems[0]?.message).toContain('npm run build:sidecar -- x64');
  });

  it('fails when the sidecar exists but is not executable', () => {
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
      '/sidecar/x64/ferry-service': {
        kind: 'binary',
        binary: thinMachO(CPU_X86_64),
        executable: false,
      },
    });
    expect(result.ok).toBe(false);
    expect(result.problems[0]?.kind).toBe('not-executable');
  });

  it('fails when the sidecar is a directory rather than a file', () => {
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
      '/sidecar/x64/ferry-service': {
        kind: 'binary' as const,
        binary: Buffer.alloc(0),
        isFile: false,
      },
    });
    expect(result.ok).toBe(false);
    expect(result.problems[0]?.kind).toBe('not-a-file');
  });

  it('catches a sidecar frozen for the wrong architecture', () => {
    // `ARCH=x64 scripts/package-release.sh` stamps arch=x64 into release.ts
    // but calls `npm run build:sidecar` with no argument, which defaults to
    // $(uname -m). Existence alone would pass this; the header does not.
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
      '/sidecar/x64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_ARM64) },
    });
    expect(result.ok).toBe(false);
    expect(result.problems[0]?.kind).toBe('arch-mismatch');
    expect(result.problems[0]?.message).toContain('arm64');
  });

  it('accepts a universal binary for both arches', () => {
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': {
        kind: 'binary' as const,
        binary: fatMachO(CPU_ARM64, CPU_X86_64),
      },
      '/sidecar/x64/ferry-service': {
        kind: 'binary' as const,
        binary: fatMachO(CPU_ARM64, CPU_X86_64),
      },
    });
    expect(result.ok).toBe(true);
  });

  it('fails when the binary header cannot be read at all', () => {
    const result = run(TWO_ARCH_CONFIG, {
      '/sidecar/arm64/ferry-service': {
        kind: 'binary' as const,
        binary: Buffer.from('not a binary'),
      },
      '/sidecar/x64/ferry-service': { kind: 'binary' as const, binary: thinMachO(CPU_X86_64) },
    });
    expect(result.ok).toBe(false);
    expect(result.problems[0]?.kind).toBe('unreadable-binary');
  });

  it('fails when the config declares no target with an explicit arch', () => {
    // The guard must never pass because it failed to look.
    const result = run('mac:\n  target:\n    - target: dmg\n', {});
    expect(result.ok).toBe(false);
    expect(result.problems.map((p) => p.kind)).toContain('implicit-arch');
  });

  it('fails when the config has no platform targets at all', () => {
    const result = run('appId: io.github.dspury.file-ferry\n', {});
    expect(result.ok).toBe(false);
    expect(result.problems[0]?.kind).toBe('no-targets');
  });

  it('fails when the config cannot be parsed', () => {
    const result = run('mac: [this is not valid\n  yaml: :', {});
    expect(result.ok).toBe(false);
    expect(result.problems[0]?.kind).toBe('unreadable-config');
  });

  it('skips the architecture check off macOS, where Mach-O does not apply', () => {
    const config = `
win:
  target:
    - target: nsis
      arch:
        - x64
`;
    const result = run(
      config,
      {
        '/sidecar/x64/ferry-service.exe': {
          kind: 'binary' as const,
          binary: Buffer.from('PE\x00\x00'),
        },
      },
      { hostPlatform: 'win32' },
    );
    expect(result.ok).toBe(true);
    expect(result.checked[0]?.platform).toBe('win');
  });
});
