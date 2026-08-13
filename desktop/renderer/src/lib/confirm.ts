/**
 * Pure destructive-confirm logic (testable without React/DOM).
 *
 * Destructive actions (move/overwrite/archive/cancel) require explicit
 * user confirmation (plan §4: "explicit destructive-action dialogs",
 * §10 Pkg7 step 4). These helpers gate a confirm dialog on a typed
 * acknowledgement phrase, so a single click can never destroy data.
 */

export interface ConfirmGate {
  readonly phrase: string;
  readonly typed: string;
  readonly exact: boolean;
}

/** Confirm is enabled only when the typed acknowledgement matches exactly. */
export function confirmEnabled(gate: ConfirmGate): boolean {
  if (!gate.exact) return true;
  return gate.typed.trim() === gate.phrase.trim();
}

/** Normalize an acknowledgement phrase for comparison. */
export function normalizePhrase(phrase: string): string {
  return phrase.trim().toLowerCase();
}

/** Standard destructive acknowledgement phrase. */
export const DESTRUCTIVE_PHRASE = 'destructive';
