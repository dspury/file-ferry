/**
 * Resolve the command used to launch the Python sidecar.
 *
 * Pure and testable so the development vs packaged resolution logic can
 * be verified without launching Electron (plan §10.6.3: package and
 * launch the frozen sidecar in development and production).
 *
 * Development launches `python -m file_ferry.service` against the workspace, so
 * the sidecar picks up source changes. The interpreter is the workspace
 * virtualenv when one is present (that is the one with the editable install),
 * otherwise `python3` from PATH; `FERRY_PYTHON` overrides both.
 *
 * Packaged builds run a platform-matched frozen executable placed at
 * `resources/sidecar/{arch}/ferry-service` by electron-builder
 * (see `desktop/build/electron-builder.yml` extraResources).
 */

export interface SidecarCommand {
  readonly executable: string;
  readonly args: string[];
  /** Working directory for the child; only set in development. */
  readonly cwd?: string;
}

/** An injected path-existence predicate (defaults to node fs). */
export type ExistsFn = (path: string) => boolean;

export interface SidecarCommandInput {
  /** Mirrors `app.isPackaged`. */
  readonly isPackaged: boolean;
  /** Mirrors `process.resourcesPath` (packaged only). */
  readonly resourcesPath: string;
  /** Repo root; used in development to find the workspace virtualenv. */
  readonly workspaceRoot: string;
  /** Mirrors `process.platform`. */
  readonly platform: NodeJS.Platform;
  /** `FERRY_PYTHON`, when the operator pinned an interpreter. */
  readonly pythonOverride?: string | undefined;
  /** Injected existence check (for tests). */
  readonly exists?: ExistsFn;
}

function defaultExists(path: string): boolean {
  // Injected at call sites in the real main; default lazily requires fs.
  // SAFETY: 'node:fs' is a builtin, so `require` returns exactly the module
  // whose type is being named here. It is required lazily rather than
  // imported so this module stays loadable in the renderer-side tests.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('node:fs') as typeof import('node:fs');
  return fs.existsSync(path);
}

/**
 * Pick the interpreter to run `-m file_ferry.service` with in development.
 *
 * The workspace virtualenv is preferred because that is where
 * `pip install -e .` puts the package; a bare `python3` only works if the
 * operator installed file-ferry into whatever interpreter PATH resolves to.
 */
export function resolveDevPython(
  workspaceRoot: string,
  platform: NodeJS.Platform,
  pythonOverride?: string | undefined,
  exists: ExistsFn = defaultExists,
): string {
  if (pythonOverride) return pythonOverride;
  const venv =
    platform === 'win32'
      ? joinPath(workspaceRoot, '.venv', 'Scripts', 'python.exe')
      : joinPath(workspaceRoot, '.venv', 'bin', 'python');
  if (exists(venv)) return venv;
  return platform === 'win32' ? 'python' : 'python3';
}

/** Build the launch command. */
export function resolveSidecarCommand(input: SidecarCommandInput): SidecarCommand {
  const exists = input.exists ?? defaultExists;
  if (!input.isPackaged) {
    return {
      executable: resolveDevPython(
        input.workspaceRoot,
        input.platform,
        input.pythonOverride,
        exists,
      ),
      args: ['-m', 'file_ferry.service'],
      cwd: input.workspaceRoot,
    };
  }
  const candidates = [
    joinPath(input.resourcesPath, 'sidecar', 'ferry-service'),
    joinPath(input.resourcesPath, 'sidecar', 'ferry-service.exe'),
  ];
  for (const candidate of candidates) {
    if (exists(candidate)) {
      return { executable: candidate, args: [] };
    }
  }
  throw new Error('sidecar executable not found in packaged resources');
}

/** Pure path join so resolution is deterministic and testable on any OS. */
export function joinPath(...parts: string[]): string {
  return parts.join('/').replace(/\/+/g, '/');
}
