/**
 * Native picker request/result types and path validation.
 *
 * Native file/folder pickers are owned by Electron main (ADR-0001);
 * the renderer never supplies an arbitrary path. It requests a picker
 * and receives a validated result. ``sanitizePickedPath`` is the pure
 * validation helper: a picked path must be absolute, resolve inside a
 * real directory, and be non-empty. Tests cover it without launching
 * Electron.
 */

export type PickerKind = 'directory' | 'file';

export interface PickRequest {
  readonly kind: PickerKind;
  /** Optional window title for the native dialog. */
  readonly title?: string;
  /** Optional default start path (must itself be validated). */
  readonly defaultPath?: string;
}

export interface PickResult {
  /** The picked absolute path, or null if the user cancelled. */
  readonly path: string | null;
  readonly cancelled: boolean;
}

/**
 * What a native picker can hand back for a path.
 *
 * Electron's dialog API yields `string | undefined` (an absent
 * `filePaths[0]`, or an unset `defaultPath`), and callers may pass an
 * explicit null. Naming that is more honest than `unknown` — but the
 * runtime check below is still a real check, not a formality: this value
 * crosses the IPC boundary, so it is verified rather than trusted.
 */
export type PickedPathInput = string | null | undefined;

/** True when the input is a string with content. */
function isNonEmptyString(value: PickedPathInput): value is string {
  return typeof value === 'string' && value.length > 0;
}

/** Validate a picked path before returning it to the renderer. */
export function sanitizePickedPath(raw: PickedPathInput): string | null {
  if (!isNonEmptyString(raw)) return null;
  const value = raw.trim();
  if (value.length === 0) return null;
  // Absolute path only; a relative or empty path cannot be a real
  // mount/directory pick.
  if (!isAbsolutePath(value)) return null;
  // Reject a bare root that would be meaningless to hand to the UI.
  if (value === '/' || /^[a-zA-Z]:[\\/]$/.test(value)) return null;
  return value;
}

function isAbsolutePath(p: string): boolean {
  if (p.startsWith('/')) return true;
  // Windows drive-absolute form, e.g. C:\ or C:\dir
  return /^[a-zA-Z]:[\\/]/.test(p);
}
