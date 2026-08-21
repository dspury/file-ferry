/**
 * Pure settings logic (testable without React/DOM).
 *
 * The Settings screen keeps form-local validation and derived-state
 * helpers here so the safety-critical behavior (no optimistic save, no
 * invalid values) is unit-testable in node.
 */
import type { AppSettings, UpdateSettingsParams } from '../../../shared/ipc-methods.js';

export const VALID_CHECKSUM_ALGOS = ['xxhash64', 'sha256'];
export const VALID_MODES = ['copy', 'move', 'link'];
export const VALID_CONFLICTS = ['skip', 'overwrite', 'rename'];
export const VALID_CODECS = ['ProRes422Proxy', 'H264', 'H265', 'ProRes422HQ', 'ProRes4444'];

export interface SettingsValidation {
  readonly valid: boolean;
  readonly errors: readonly string[];
}

/**
 * Validate a settings draft before it is sent to the sidecar. Only the
 * fields that are selectable/driven by the UI are constrained here; free
 * text (paths, template) is validated for non-emptiness only.
 */
export function validateSettings(settings: AppSettings): SettingsValidation {
  const errors: string[] = [];
  if (!VALID_CHECKSUM_ALGOS.includes(settings.checksumAlgo)) {
    errors.push(`unknown checksum algorithm: ${settings.checksumAlgo}`);
  }
  if (!VALID_MODES.includes(settings.organizeMode)) {
    errors.push(`unknown organize mode: ${settings.organizeMode}`);
  }
  if (!VALID_CONFLICTS.includes(settings.organizeOnConflict)) {
    errors.push(`unknown conflict policy: ${settings.organizeOnConflict}`);
  }
  if (!VALID_CODECS.includes(settings.proxyCodec)) {
    errors.push(`unknown proxy codec: ${settings.proxyCodec}`);
  }
  if (!Number.isInteger(settings.proxyHeight) || settings.proxyHeight < 1) {
    errors.push('proxy height must be a positive integer');
  }
  if (settings.organizeTemplate.trim().length === 0) {
    errors.push('organize template must not be empty');
  }
  return { valid: errors.length === 0, errors };
}

/** Build the update payload for the current settings (only non-null). */
export function toUpdateParams(settings: AppSettings): UpdateSettingsParams {
  return {
    proxyCodec: settings.proxyCodec,
    proxyHeight: settings.proxyHeight,
    checksumAlgo: settings.checksumAlgo,
    resolvePath: settings.resolvePath,
    ffmpegPath: settings.ffmpegPath,
    organizeTemplate: settings.organizeTemplate,
    organizeMode: settings.organizeMode,
    organizeOnConflict: settings.organizeOnConflict,
  };
}

/** True when a draft differs from the persisted baseline (for dirty state). */
export function hasChanges(draft: AppSettings, baseline: AppSettings): boolean {
  return JSON.stringify(toUpdateParams(draft)) !== JSON.stringify(toUpdateParams(baseline));
}
