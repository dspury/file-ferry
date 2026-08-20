/**
 * Resolve the command used to launch the Python sidecar.
 *
 * Pure and testable so the development vs packaged resolution logic can
 * be verified without launching Electron (plan §10.6.3: package and
 * launch the frozen sidecar in development and production).
 *
 * Development launches `python -m ferry.service` against the
 * workspace (so the sidecar picks up source changes). Packaged builds
 * run a platform-matched frozen executable placed at
 * `resources/sidecar/{arch}/ferry-service` by electron-builder
 * (see `desktop/build/electron-builder.yml` extraResources).
 */

export interface SidecarCommand {
  readonly executable: string;
  readonly args: string[];
}

/** An injected path-existence predicate (defaults to node fs). */
export type ExistsFn = (path: string) => boolean;

function defaultExists(path: string): boolean {
  // Injected at call sites in the real main; default lazily requires fs.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('node:fs') as typeof import('node:fs');
  return fs.existsSync(path);
}

/**
 * Build the launch command.
 *
 * @param isPackaged mirrors ``app.isPackaged``
 * @param resourcesPath mirrors ``process.resourcesPath`` (packaged only)
 * @param processExecPath mirrors ``process.execPath``
 * @param exists optional injected existence check (for tests)
 */
export function resolveSidecarCommand(
  isPackaged: boolean,
  resourcesPath: string,
  processExecPath: string,
  exists: ExistsFn = defaultExists,
): SidecarCommand {
  if (!isPackaged) {
    return {
      executable: processExecPath,
      args: ['-m', 'ferry.service'],
    };
  }
  const candidates = [
    joinPath(resourcesPath, 'sidecar', 'ferry-service'),
    joinPath(resourcesPath, 'sidecar', 'ferry-service.exe'),
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
