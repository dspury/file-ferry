/**
 * Pure virtual-list windowing math (testable without React/DOM).
 */

export interface WindowResult {
  readonly start: number;
  readonly end: number;
  readonly totalHeight: number;
}

/**
 * Compute the visible row window for a scroll position. Clamped to the
 * item count and total height so out-of-bounds scroll values are safe.
 */
export function windowForScroll(
  scrollTop: number,
  viewportHeight: number,
  rowHeight: number,
  itemCount: number,
  overscan: number,
): WindowResult {
  if (itemCount <= 0 || rowHeight <= 0 || viewportHeight <= 0) {
    return { start: 0, end: 0, totalHeight: 0 };
  }
  const totalHeight = itemCount * rowHeight;
  const firstVisible = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const lastVisible = Math.min(
    itemCount,
    Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan,
  );
  return {
    start: firstVisible,
    end: lastVisible,
    totalHeight,
  };
}

/** Clamp a scroll offset into the valid range for a total height. */
export function clampScroll(
  scrollTop: number,
  totalHeight: number,
  viewportHeight: number,
): number {
  const max = Math.max(0, totalHeight - viewportHeight);
  return Math.max(0, Math.min(scrollTop, max));
}
