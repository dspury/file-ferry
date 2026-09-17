/**
 * R-1: no left-edge colour bars on `.stat`, `.banner`, or `.nav__item`.
 *
 * SR-1 forbids a lone coloured edge as a state indicator. jsdom does not
 * apply the stylesheet, so this is a textual guard over `styles.css` (the
 * same approach the brand-token test uses): the three selectors and their
 * state modifiers must not reach for `border-left`, and the replacement
 * signals must exist — the stat value's tone colour, and a full-perimeter
 * border on the banner.
 *
 * R-7 moved the stat tile further: SR-5 makes an individual statistic
 * element-scale, so it now has no border at all, and its state is carried
 * entirely by the value text. The banner is a message plate and keeps its
 * full perimeter for the same reason it always did.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const raw = readFileSync(join(import.meta.dirname, '..', 'renderer', 'src', 'styles.css'), 'utf8');
const css = raw.replace(/\/\*[\s\S]*?\*\//g, '');

/** True if any rule whose selector mentions `name` sets a border-left. */
function hasLeftEdge(name: string): boolean {
  const re = new RegExp(`\\.${name}[^{}]*\\{[^}]*border-left`, 'g');
  return re.test(css);
}

const STATES = ['active', 'ok', 'warn', 'danger', 'cancelled', 'attention'];

describe('R-1 no left-edge colour bars', () => {
  it('removes the bar from the stat tile, the banner, and the nav item', () => {
    expect(hasLeftEdge('stat')).toBe(false);
    expect(hasLeftEdge('banner')).toBe(false);
    expect(hasLeftEdge('nav__item')).toBe(false);
  });

  it('keeps every stat state distinguishable by the value text colour', () => {
    for (const state of STATES) {
      const re = new RegExp(`\\.stat--${state} \\.stat__value\\s*\\{[^}]*color:`);
      expect(re.test(css), `stat--${state} value colour`).toBe(true);
    }
  });

  it('leaves the stat tile unboxed (R-7) and the banner with a full perimeter', () => {
    // SR-5: element-scale statistics get no rim and no box; their state is
    // the value colour asserted above.
    expect(/\.stat\s*\{[^}]*border:\s*1px solid/.test(css)).toBe(false);
    // The banner is a message plate, not an element-scale chip.
    expect(/\.banner\s*\{[^}]*border:\s*1px solid/.test(css)).toBe(true);
  });

  it('gives every banner state a full border, not just a colour', () => {
    for (const state of ['danger', 'warn', 'ok', 'attention', 'info']) {
      const re = new RegExp(`\\.banner--${state}\\s*\\{[^}]*border-color:`);
      expect(re.test(css), `banner--${state} border`).toBe(true);
    }
  });

  it('does not animate a border colour on the nav item any more', () => {
    const re = /\.nav__item\s*\{[^}]*transition:[^;]*border-color/;
    expect(re.test(css)).toBe(false);
  });
});
