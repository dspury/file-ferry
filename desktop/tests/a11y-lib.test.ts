/**
 * Tests for the pure accessibility logic introduced with the Rams design
 * review fixes (issues #64–#69): the modal focus-trap arithmetic and the
 * ARIA progress-value clamp. These run in node without React/DOM.
 */
import { describe, expect, it } from 'vitest';
import { nextFocusIndex, isTrapKey, FOCUSABLE_SELECTOR } from '../renderer/src/lib/focus-trap.js';
import { progressPercent } from '../renderer/src/lib/activity.js';

describe('nextFocusIndex', () => {
  it('wraps forward off the last element', () => {
    expect(nextFocusIndex(2, 3, false)).toBe(0);
  });

  it('wraps backward off the first element', () => {
    expect(nextFocusIndex(0, 3, true)).toBe(2);
  });

  it('defers to the browser in the middle of the range', () => {
    expect(nextFocusIndex(1, 3, false)).toBeNull();
    expect(nextFocusIndex(1, 3, true)).toBeNull();
  });

  it('pulls focus back in when it is outside the trap', () => {
    expect(nextFocusIndex(-1, 3, false)).toBe(0);
    expect(nextFocusIndex(-1, 3, true)).toBe(2);
  });

  it('pins a single focusable element in both directions', () => {
    expect(nextFocusIndex(0, 1, false)).toBe(0);
    expect(nextFocusIndex(0, 1, true)).toBe(0);
  });

  it('does nothing when the dialog has nothing focusable', () => {
    expect(nextFocusIndex(-1, 0, false)).toBeNull();
    expect(nextFocusIndex(0, 0, true)).toBeNull();
  });
});

describe('FOCUSABLE_SELECTOR', () => {
  it('skips disabled controls', () => {
    expect(FOCUSABLE_SELECTOR).toContain('button:not([disabled])');
  });

  it('excludes tabindex="-1", which Tab cannot reach', () => {
    expect(FOCUSABLE_SELECTOR).toContain('[tabindex]:not([tabindex="-1"])');
  });
});

describe('isTrapKey', () => {
  it('claims Tab and nothing else', () => {
    expect(isTrapKey('Tab')).toBe(true);
    expect(isTrapKey('Escape')).toBe(false);
    expect(isTrapKey('a')).toBe(false);
  });
});

describe('progressPercent', () => {
  it('converts a fraction to a whole percentage', () => {
    expect(progressPercent(0)).toBe(0);
    expect(progressPercent(0.5)).toBe(50);
    expect(progressPercent(1)).toBe(100);
  });

  it('rounds to an integer, as aria-valuenow expects', () => {
    expect(progressPercent(1 / 3)).toBe(33);
  });

  it('clamps out-of-range input so aria-valuenow stays within min/max', () => {
    expect(progressPercent(-1)).toBe(0);
    expect(progressPercent(2)).toBe(100);
  });

  it('treats a non-finite fraction as zero rather than emitting NaN', () => {
    expect(progressPercent(Number.NaN)).toBe(0);
    expect(progressPercent(Number.POSITIVE_INFINITY)).toBe(100);
    expect(progressPercent(Number.NEGATIVE_INFINITY)).toBe(0);
  });
});
