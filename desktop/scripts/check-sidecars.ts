#!/usr/bin/env node --experimental-strip-types
/**
 * Fail the build when an arch electron-builder is about to package has no
 * usable frozen sidecar.
 *
 * ## Why this exists
 *
 * `build/electron-builder.yml` carries:
 *
 *     extraResources:
 *       - from: 'sidecar/${arch}'
 *
 * When that directory does not exist, **electron-builder does not fail.** It
 * logs a single informational line and carries on:
 *
 *     • file source doesn't exist  from=.../desktop/sidecar/x64
 *     • file source doesn't exist  from=.../desktop/sidecar/x64
 *     skipped macOS application code signing  reason=
 *     === PACKAGE EXIT 0 ===
 *
 * The result is a structurally complete `ferry.app` with no
 * `Contents/Resources/sidecar/` directory at all. It installs, it launches,
 * and it is dead: `electron/sidecar-command.ts` resolves the sidecar by
 * probing those two paths and throws on neither:
 *
 *     throw new Error('sidecar executable not found in packaged resources');
 *
 * Reproduced on 2026-10-05 at `release/mac/ferry.app` — no sidecar directory,
 * build exit 0. `release/ferry-0.0.0.dmg` (x64, 138MB) had already been
 * produced this way on 2026-09-18 and was sitting in the release directory.
 *
 * `scripts/verify-packaged.sh` would have caught it, but it is a post-hoc
 * check that takes a path by hand and nothing calls it during packaging. This
 * is the pre-flight half, and it is the half that can still be cheap.
 *
 * This is the same defect class as declaring Windows and Linux targets that
 * nothing had ever built (removed in #203): a declared target that produces a
 * bundle missing the thing that makes it work.
 *
 * ## What it checks
 *
 * For every `(platform, arch)` the config declares:
 *
 *   1. the sidecar file exists, is a file, and is executable;
 *   2. on macOS, the Mach-O header's CPU types actually include the declared
 *      arch.
 *
 * Check 2 exists because of a second, quieter lie:
 * `scripts/package-release.sh` accepts `ARCH=x64` and passes it to the
 * provenance stamp, but called `npm run build:sidecar` with no argument — and
 * that script defaults to `$(uname -m)`. So `ARCH=x64 scripts/package-release.sh`
 * froze an arm64 binary, stamped `arch=x64` into `release.ts`, and would now
 * pass a pure existence check. A build that reports the wrong architecture in
 * its own diagnostics is worse than one that fails.
 *
 * A target that declares no explicit `arch` is also a failure. electron-builder
 * substitutes its own default, and the point of this guard is that what gets
 * built is never a surprise.
 *
 * ## Why TypeScript with no build step
 *
 * Run directly by `node`, which strips the types (Node >= 22.18). It has to
 * work before anything is compiled, because it guards the step that compiles
 * the rest of the desktop. Keeping it as `.ts` rather than `.mjs` is what lets
 * the type guards below be real `value is` predicates, which is what the
 * `anti-slop/no-runtime-typeof` rule is asking for.
 *
 * ## Failure direction
 *
 * Everything here fails **loudly**. An unparseable config, an unrecognised
 * Mach-O magic, an empty arch list — all exit non-zero. This guard must never
 * pass because it failed to look.
 *
 * Usage:  node scripts/check-sidecars.ts [--config <path>] [--sidecar-root <dir>]
 */

import { readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { load } from 'js-yaml';

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONFIG = resolve(HERE, '..', 'build', 'electron-builder.yml');
const DEFAULT_SIDECAR_ROOT = resolve(HERE, '..', 'sidecar');

/** electron-builder platform blocks that can carry a `target` list. */
const PLATFORM_BLOCKS = ['mac', 'win', 'linux'] as const;

/** Frozen executable name per platform. Mirrors build-sidecar.sh output and
 *  the two candidates in electron/sidecar-command.ts. */
const SIDECAR_NAME = {
  mac: 'ferry-service',
  linux: 'ferry-service',
  win: 'ferry-service.exe',
} satisfies Record<string, string>;

/**
 * Any value a parsed YAML document can contain.
 *
 * Same reasoning as `JsonValue` in shared/ipc-schema.ts: the config is parsed,
 * not typed, so every leaf is a scalar, a sequence, or a mapping. Naming that
 * here gives `declaredTargets` something real to narrow, instead of `unknown`
 * with `typeof` scattered through the logic.
 */
export type ConfigNode =
  string | number | boolean | null | ConfigNode[] | { readonly [key: string]: ConfigNode };

/**
 * A slot in the config that may be absent.
 *
 * `noUncheckedIndexedAccess` is on, so every `mapping['key']` is this rather
 * than a `ConfigNode`. The guards take it directly instead of each caller
 * having to re-narrow the same maybe.
 */
export type ConfigSlot = ConfigNode | undefined;

function isConfigMapping(value: ConfigSlot): value is { readonly [key: string]: ConfigNode } {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isConfigSequence(value: ConfigSlot): value is ConfigNode[] {
  return Array.isArray(value);
}

function isConfigString(value: ConfigSlot): value is string {
  return typeof value === 'string';
}

/** Collapse the spellings electron-builder and uname use onto one name. */
export function normaliseArch(name: string): string {
  const key = name.trim().toLowerCase();
  switch (key) {
    case 'x64':
    case 'x86_64':
    case 'amd64':
      return 'x64';
    case 'arm64':
    case 'aarch64':
      return 'arm64';
    case 'ia32':
    case 'x86':
    case 'i386':
      return 'ia32';
    default:
      return key;
  }
}

/** CPU_TYPE values from <mach/machine.h>. */
const CPU_TYPE_X86 = 0x00000007;
const CPU_TYPE_X86_64 = 0x01000007;
const CPU_TYPE_ARM = 0x0000000c;
const CPU_TYPE_ARM64 = 0x0100000c;

const MACH_MAGIC_32 = 0xfeedface;
const MACH_MAGIC_64 = 0xfeedfacf;
const CIGAM_32 = 0xcefaedfe;
const CIGAM_64 = 0xcffaedfe;
const FAT_MAGIC = 0xcafebabe;
const FAT_MAGIC_64 = 0xbebafeca;

function archForCpuType(cpu: number): string | null {
  switch (cpu) {
    case CPU_TYPE_X86_64:
      return 'x64';
    case CPU_TYPE_ARM64:
      return 'arm64';
    case CPU_TYPE_X86:
      return 'ia32';
    case CPU_TYPE_ARM:
      return 'arm';
    default:
      return null;
  }
}

/**
 * Read the CPU architectures out of a Mach-O or fat binary.
 *
 * Returns the set of normalised arch names. Throws on anything unrecognised —
 * a header we cannot parse must not read as "matches", and must not read as
 * "no architectures" either, because both would let a wrong-arch binary pass.
 */
export function readMachOArchitectures(buffer: Buffer): Set<string> {
  if (buffer.length < 8) {
    throw new Error(`file is ${buffer.length} bytes; too short to be a Mach-O binary`);
  }
  const magic = buffer.readUInt32LE(0);
  const found = new Set<string>();
  const add = (cpu: number): void => {
    const arch = archForCpuType(cpu);
    if (arch !== null) found.add(arch);
  };

  if (magic === MACH_MAGIC_64 || magic === MACH_MAGIC_32) {
    add(buffer.readUInt32LE(4));
  } else if (magic === CIGAM_64 || magic === CIGAM_32) {
    add(buffer.readUInt32BE(4));
  } else if (magic === FAT_MAGIC || magic === FAT_MAGIC_64) {
    // Fat headers are big-endian regardless of the slices they contain.
    const nfat = buffer.readUInt32BE(4);
    if (nfat === 0) throw new Error('fat Mach-O declares 0 architectures');
    for (let i = 0; i < nfat; i += 1) {
      const at = 8 + i * 20;
      if (at + 4 > buffer.length) {
        throw new Error(`fat Mach-O claims ${nfat} architectures but the header is truncated`);
      }
      add(buffer.readUInt32BE(at));
    }
  } else {
    throw new Error(`not a Mach-O binary: magic 0x${magic.toString(16).padStart(8, '0')}`);
  }

  if (found.size === 0) {
    throw new Error('Mach-O header parsed but named no known architecture');
  }
  return found;
}

/** The `arch` list of a config slot, as a sequence of strings. */
function archListOf(value: ConfigSlot): string[] | undefined {
  if (value === undefined || value === null) return undefined;
  const entries = isConfigSequence(value) ? value : [value];
  return entries.filter(isConfigString);
}

export interface SidecarProblem {
  readonly kind:
    | 'unreadable-config'
    | 'no-targets'
    | 'implicit-arch'
    | 'missing'
    | 'not-a-file'
    | 'not-executable'
    | 'unreadable-binary'
    | 'arch-mismatch';
  readonly message: string;
}

export type Platform = (typeof PLATFORM_BLOCKS)[number];

export interface DeclaredTarget {
  readonly platform: Platform;
  readonly arch: string;
  readonly target: string;
}

export interface CheckedSidecar extends DeclaredTarget {
  readonly path: string;
}

export interface CheckSidecarsResult {
  readonly ok: boolean;
  readonly checked: readonly CheckedSidecar[];
  readonly problems: readonly SidecarProblem[];
}

/**
 * Every `(platform, arch)` the config declares, plus config-level problems.
 */
export interface DeclaredTargets {
  readonly targets: DeclaredTarget[];
  readonly problems: SidecarProblem[];
}

/**
 * Every `(platform, arch)` the config declares, plus config-level problems.
 */
export function declaredTargets(config: ConfigNode): DeclaredTargets {
  const targets: DeclaredTarget[] = [];
  const problems: SidecarProblem[] = [];

  for (const platform of PLATFORM_BLOCKS) {
    const block = isConfigMapping(config) ? config[platform] : undefined;
    if (!isConfigMapping(block)) continue;
    // electron-builder allows two spellings: `target: AppImage` (a bare
    // string, with `arch` as its sibling) and
    // `target: { target: AppImage, arch: [...] }`. Reading only the nested
    // form would silently under-check every config written in the shorthand,
    // so both are read and a per-target value overrides the platform one.
    const blockArch = archListOf(block['arch']);
    const entries = isConfigSequence(block['target'])
      ? block['target']
      : block['target'] === undefined || block['target'] === null
        ? []
        : [block['target']];

    for (const entry of entries) {
      // Two spellings: `target: AppImage` (a bare string, with `arch` as its
      // sibling) and `target: { target: AppImage, arch: [...] }`. Reading only
      // the nested form would silently under-check every config written in the
      // shorthand, so both are read and a per-target value overrides the
      // platform one.
      const shorthand = isConfigString(entry);
      const mapping = shorthand ? undefined : isConfigMapping(entry) ? entry : undefined;
      const named = mapping === undefined ? undefined : mapping['target'];
      const label = shorthand ? entry : isConfigString(named) ? named : '<unnamed>';
      const rawArch =
        (mapping === undefined ? undefined : archListOf(mapping['arch'])) ?? blockArch;

      if (rawArch === undefined) {
        problems.push({
          kind: 'implicit-arch',
          message:
            `${platform} target "${label}" declares no explicit \`arch\`. ` +
            'electron-builder would substitute its own default, which is exactly the ' +
            'ambiguity this guard exists to remove — state the arch.',
        });
        continue;
      }

      for (const arch of rawArch) {
        targets.push({ platform, arch: normaliseArch(arch), target: label });
      }
    }
  }

  return { targets, problems };
}

/** The slice of `fs.Stats` this guard reads, so tests can stand in for it. */
export interface FileProbe {
  isFile(): boolean;
  readonly mode: number;
}

/**
 * The filesystem this guard reads through.
 *
 * Two readers rather than one `readFile` returning `string | Buffer`: the
 * contract then states up front which representation each caller gets, so
 * neither has to re-establish it with a runtime check.
 */
export interface SidecarEnvironment {
  readonly configPath: string;
  readonly sidecarRoot: string;
  readonly hostPlatform: NodeJS.Platform;
  readonly readText: (path: string) => string;
  readonly readBinary: (path: string) => Buffer;
  readonly fileExists: (path: string) => FileProbe | null;
}

/** The real filesystem, used by the CLI. */
const REAL_FS: Pick<SidecarEnvironment, 'readText' | 'readBinary' | 'fileExists'> = {
  readText: (path: string) => readFileSync(path, 'utf8'),
  readBinary: (path: string) => readFileSync(path),
  fileExists: (path: string) => {
    try {
      return statSync(path);
    } catch {
      return null;
    }
  },
};

/**
 * Check every declared target has a usable sidecar of the right architecture.
 *
 * The environment is injected so the tests exercise this against in-memory
 * fixtures rather than a real build tree — no test here can be satisfied by a
 * stale `desktop/sidecar/`.
 */
export function checkSidecars(environment: SidecarEnvironment): CheckSidecarsResult {
  const { configPath, sidecarRoot, hostPlatform, readText, readBinary, fileExists } = environment;
  const problems: SidecarProblem[] = [];
  const checked: CheckedSidecar[] = [];

  let config: ConfigNode;
  try {
    // SAFETY: js-yaml types `load` as `unknown`, but a parsed YAML document
    // contains only scalars, sequences and mappings — which is exactly
    // `ConfigNode`. Every field this guard relies on is re-checked by the type
    // guards in `declaredTargets`, so a document that breaks the assumption is
    // caught there rather than trusted here.
    config = load(readText(configPath)) as ConfigNode;
  } catch (error) {
    return {
      ok: false,
      checked,
      problems: [
        {
          kind: 'unreadable-config',
          message: `could not read or parse ${configPath}: ${error instanceof Error ? error.message : String(error)}`,
        },
      ],
    };
  }

  const { targets, problems: configProblems } = declaredTargets(config);
  problems.push(...configProblems);

  if (targets.length === 0) {
    problems.push({
      kind: 'no-targets',
      message:
        `no platform target with an explicit arch found in ${configPath}. ` +
        'Either the config moved its targets or the guard needs updating — refusing to pass.',
    });
    return { ok: false, checked, problems };
  }

  for (const { platform, arch, target } of targets) {
    const name = SIDECAR_NAME[platform];
    if (name === undefined) continue;
    const path = join(sidecarRoot, arch, name);
    const label = `${platform}/${arch} (${target})`;

    const probe = fileExists(path);
    if (probe === null) {
      problems.push({
        kind: 'missing',
        message:
          `${label}: no sidecar at ${path}\n` +
          '  electron-builder would log "file source doesn\'t exist", exit 0, and ship a\n' +
          '  bundle that dies on launch. Build it with:  npm run build:sidecar -- ' +
          arch,
      });
      continue;
    }
    if (!probe.isFile()) {
      problems.push({
        kind: 'not-a-file',
        message: `${label}: ${path} exists but is not a regular file.`,
      });
      continue;
    }
    if ((probe.mode & 0o111) === 0) {
      problems.push({
        kind: 'not-executable',
        message: `${label}: ${path} is not executable (mode ${(probe.mode & 0o777).toString(8)}).`,
      });
      continue;
    }

    if (platform === 'mac' && hostPlatform === 'darwin') {
      let archs: Set<string>;
      try {
        archs = readMachOArchitectures(readBinary(path));
      } catch (error) {
        problems.push({
          kind: 'unreadable-binary',
          message: `${label}: could not read the Mach-O header of ${path}: ${error instanceof Error ? error.message : String(error)}`,
        });
        continue;
      }
      if (!archs.has(arch)) {
        problems.push({
          kind: 'arch-mismatch',
          message:
            `${label}: ${path} is a ${[...archs].join('/')} binary, not ${arch}.\n` +
            '  A bundle stamped with the wrong architecture in its own diagnostics is worse\n' +
            '  than one that fails. Check whether ARCH reached scripts/build-sidecar.sh.',
        });
        continue;
      }
    }

    checked.push({ platform, arch, target, path });
  }

  return { ok: problems.length === 0, checked, problems };
}

interface CliOverrides {
  readonly configPath?: string | undefined;
  readonly sidecarRoot?: string | undefined;
}

function parseArgs(argv: readonly string[]): CliOverrides {
  let configPath: string | undefined;
  let sidecarRoot: string | undefined;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--config') configPath = resolve(argv[++i] ?? '');
    else if (argv[i] === '--sidecar-root') sidecarRoot = resolve(argv[++i] ?? '');
  }
  return { configPath, sidecarRoot };
}

export function main(argv: readonly string[]): number {
  const overrides = parseArgs(argv);
  const result = checkSidecars({
    configPath: overrides.configPath ?? DEFAULT_CONFIG,
    sidecarRoot: overrides.sidecarRoot ?? DEFAULT_SIDECAR_ROOT,
    hostPlatform: process.platform,
    ...REAL_FS,
  });

  if (result.ok) {
    for (const { platform, arch, target } of result.checked) {
      process.stdout.write(`  ok  ${platform}/${arch}  ${target}\n`);
    }
    process.stdout.write(
      `check-sidecars: ${result.checked.length} target(s) have a usable sidecar\n`,
    );
    return 0;
  }

  process.stderr.write('check-sidecars: FAILED\n\n');
  for (const { kind, message } of result.problems) {
    process.stderr.write(`  [${kind}] ${message}\n\n`);
  }
  process.stderr.write(
    'electron-builder does not fail on a missing sidecar — it ships a bundle that\n' +
      'cannot start. This check is the only thing standing between a typo in the\n' +
      'arch list and that bundle reaching a user.\n',
  );
  return 1;
}

const invokedDirectly =
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  process.exit(main(process.argv.slice(2)));
}
