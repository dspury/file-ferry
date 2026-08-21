/**
 * Local diagnostics owned by Electron main.
 *
 * ADR-0001 / plan §8.1: main owns diagnostic logs stored locally and the
 * "open diagnostic folder" affordance. This module:
 *   - ensures the per-app log directory exists under appData
 *   - exposes the sidecar stderr/stdout append sink used by the supervisor
 *   - provides an openDiagnosticFolder handler backed by shell.openPath
 */

import { app, shell } from 'electron';
import { mkdirSync, appendFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { logDirectoryName } from '../shared/diagnostics.js';

/** Resolve (and create, if needed) the diagnostic log directory. */
export function ensureLogDir(): string {
  const logDir = join(app.getPath('userData'), logDirectoryName());
  mkdirSync(logDir, { recursive: true });
  return logDir;
}

/** Append a log line to a named log file in the diagnostics dir. */
export function appendLog(logDir: string, fileName: string, line: string): void {
  const file = join(logDir, fileName);
  appendFileSync(file, `${line}\n`);
}

/** Count log files present in the diagnostics dir. */
export function countLogFiles(logDir: string): number {
  try {
    return readdirSync(logDir).length;
  } catch {
    return 0;
  }
}

/** Open the diagnostics folder in the platform file manager. */
export async function openDiagnosticFolder(logDir: string): Promise<void> {
  await shell.openPath(logDir);
}
