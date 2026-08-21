/**
 * Pure navigation / keyboard logic (testable without React/DOM).
 *
 * The nav supports arrow-key + Enter navigation (plan §10 Pkg7 step 4
 * keyboard accessibility). All index math is pure so it is unit-testable.
 */

/** Find the index of the active view in the view list, clamped to bounds. */
export function viewIndex(activeId: string, ids: readonly string[]): number {
  const idx = ids.indexOf(activeId);
  return idx === -1 ? 0 : idx;
}

/** Move the index within [0, n-1], wrapping at the ends. */
export function moveIndex(current: number, delta: number, total: number): number {
  if (total <= 0) return 0;
  return (current + delta + total) % total;
}

export type NavKeyAction = 'next' | 'prev' | 'activate' | 'none';

/**
 * Map a keydown event to a nav action. Supports ArrowDown/ArrowUp for
 * next/prev and Enter/Space for activate.
 */
export function keyToAction(key: string, ctrl = false, alt = false): NavKeyAction {
  if (ctrl || alt) return 'none';
  if (key === 'ArrowDown') return 'next';
  if (key === 'ArrowUp') return 'prev';
  if (key === 'Enter' || key === ' ') return 'activate';
  return 'none';
}
