/**
 * Pure focus-trap logic (testable without React/DOM).
 *
 * A modal dialog must keep Tab focus inside itself (WCAG 2.4.3) — otherwise
 * a keyboard user tabs straight out into the background UI while the dialog
 * is still up. The DOM wiring lives in the component; the index arithmetic
 * and the "should we intervene at all" decision are pure and live here.
 */

/**
 * CSS selector for elements that can hold keyboard focus.
 *
 * `[tabindex="-1"]` is deliberately excluded: it is programmatically
 * focusable but not reachable by Tab, so trapping onto it would strand the
 * user on an element they cannot leave by keyboard.
 */
export const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * Where Tab should land, given the currently focused index in the trap.
 *
 * Returns the index to focus, or `null` to let the browser handle it
 * normally. We only intervene at the edges — wrapping last→first on Tab and
 * first→last on Shift+Tab — so ordinary movement inside the dialog keeps the
 * browser's own ordering.
 */
export function nextFocusIndex(current: number, total: number, shift: boolean): number | null {
  if (total <= 0) return null;
  // Focus is somewhere outside the known set (or nowhere): pull it back in.
  if (current < 0) return shift ? total - 1 : 0;
  if (total === 1) return 0;
  if (!shift && current === total - 1) return 0;
  if (shift && current === 0) return total - 1;
  return null;
}

/** True when a keydown should be handled by the trap. */
export function isTrapKey(key: string): boolean {
  return key === 'Tab';
}
