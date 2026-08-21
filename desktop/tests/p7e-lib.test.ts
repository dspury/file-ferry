/**
 * Tests for the pure Package 7e logic (keyboard nav, virtualized lists,
 * diagnostics, destructive confirm). These run in node without React/DOM.
 */
import { describe, expect, it } from 'vitest';
import { viewIndex, moveIndex, keyToAction } from '../renderer/src/lib/nav.js';
import { windowForScroll, clampScroll } from '../renderer/src/lib/virtualize.js';
import { buildReportText, canCopy, diagnosticFileName } from '../renderer/src/lib/diagnostics.js';
import { confirmEnabled, normalizePhrase } from '../renderer/src/lib/confirm.js';

describe('nav', () => {
  const ids = ['home', 'projects', 'ingest', 'activity'];

  it('viewIndex finds the active index, defaulting to 0', () => {
    expect(viewIndex('projects', ids)).toBe(1);
    expect(viewIndex('unknown', ids)).toBe(0);
  });

  it('moveIndex wraps at both ends', () => {
    expect(moveIndex(1, 1, 4)).toBe(2);
    expect(moveIndex(3, 1, 4)).toBe(0); // wrap forward
    expect(moveIndex(0, -1, 4)).toBe(3); // wrap backward
    expect(moveIndex(0, 0, 4)).toBe(0);
    expect(moveIndex(0, 1, 0)).toBe(0); // empty
  });

  it('keyToAction maps arrows and activate', () => {
    expect(keyToAction('ArrowDown')).toBe('next');
    expect(keyToAction('ArrowUp')).toBe('prev');
    expect(keyToAction('Enter')).toBe('activate');
    expect(keyToAction(' ')).toBe('activate');
    expect(keyToAction('a')).toBe('none');
    // Modifier keys disable nav.
    expect(keyToAction('ArrowDown', true)).toBe('none');
    expect(keyToAction('ArrowDown', false, true)).toBe('none');
  });
});

describe('virtualize', () => {
  it('windows the visible rows with overscan and total height', () => {
    const w = windowForScroll(0, 400, 40, 100, 5);
    expect(w.totalHeight).toBe(4000);
    expect(w.start).toBe(0);
    // 400/40=10 visible + 5 overscan.
    expect(w.end).toBe(15);
  });

  it('clamps to item count at the bottom', () => {
    const w = windowForScroll(100 * 40, 400, 40, 100, 5);
    expect(w.end).toBe(100);
    expect(w.start).toBeLessThan(100);
  });

  it('returns empty window for zero items or zero height', () => {
    expect(windowForScroll(0, 400, 40, 0, 5)).toEqual({ start: 0, end: 0, totalHeight: 0 });
    expect(windowForScroll(0, 0, 40, 10, 5)).toEqual({ start: 0, end: 0, totalHeight: 0 });
  });

  it('clampScroll bounds within total height', () => {
    expect(clampScroll(5000, 4000, 400)).toBe(3600);
    expect(clampScroll(-10, 4000, 400)).toBe(0);
    expect(clampScroll(100, 4000, 400)).toBe(100);
  });
});

describe('diagnostics', () => {
  it('buildReportText prepends a header', () => {
    const text = buildReportText({
      summary: 'platform=darwin\nprotocol=1',
      generatedAt: '2026-08-12T17:30:00Z',
      appVersion: '0.0.0',
    });
    expect(text).toContain('media-mate diagnostic report');
    expect(text).toContain('platform=darwin');
    expect(text).toContain('app version: 0.0.0');
  });

  it('canCopy requires non-empty summary', () => {
    expect(canCopy({ summary: 'x', generatedAt: '', appVersion: '' })).toBe(true);
    expect(canCopy({ summary: '   ', generatedAt: '', appVersion: '' })).toBe(false);
    expect(canCopy(null)).toBe(false);
  });

  it('diagnosticFileName is stamp-derived and safe', () => {
    expect(diagnosticFileName('2026-08-12T17:30:00Z')).toMatch(/media-mate-diagnostics-\d+\.txt/);
    expect(diagnosticFileName('bad')).toContain('unknown');
  });
});

describe('confirm', () => {
  it('confirmEnabled gates on exact phrase when exact', () => {
    expect(confirmEnabled({ phrase: 'move', typed: 'move', exact: true })).toBe(true);
    expect(confirmEnabled({ phrase: 'move', typed: 'mve', exact: true })).toBe(false);
    expect(confirmEnabled({ phrase: 'move', typed: '', exact: true })).toBe(false);
  });

  it('confirmEnabled ignores phrase when not exact', () => {
    expect(confirmEnabled({ phrase: 'move', typed: '', exact: false })).toBe(true);
  });

  it('normalizePhrase trims and lowercases', () => {
    expect(normalizePhrase('  Move ')).toBe('move');
  });
});
