/**
 * R-2 breakpoints, pinned as a guard on the sheet.
 *
 * jsdom does not evaluate media queries, so this cannot be a render test —
 * the real check is SR-4 (boot the app and resize it; see the PR's measured
 * table). What this does hold in place is the *contract* the CSS must keep:
 * the collapse breakpoint, the visually-hidden label that carries the
 * accessible name through it, the stat floor, the table's own scroll, and the
 * title truncation that stops the header colliding at the 600px floor. It is
 * the same style of textual pin the brand-token test uses for styles.css.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(import.meta.dirname, '..', 'renderer', 'src', 'styles.css'), 'utf8');

/** The body of the first `@media (max-width: Npx) { ... }` block, by regex. */
function mediaBlock(css: string, maxWidth: number): string {
  const start = css.indexOf(`@media (max-width: ${maxWidth}px)`);
  expect(start).toBeGreaterThanOrEqual(0);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open, i + 1);
    }
  }
  throw new Error('unterminated media block');
}

describe('R-2 narrow-width breakpoints', () => {
  const narrow = mediaBlock(css, 999);

  it('collapses the rail to an icon strip', () => {
    expect(narrow).toMatch(/--nav-w:\s*64px/);
  });

  it('visually hides the label rather than removing it, so the name survives', () => {
    expect(narrow).toMatch(/\.nav__label\s*\{[^}]*clip:/);
  });

  it('gives the collapsed active item a plain raised plate', () => {
    // On a square cell the left-to-right gradient has no width to read; the
    // R-1 removal of the accent edge is guarded separately in edge-bars.
    expect(narrow).toMatch(/\.nav__item--active\s*\{[^}]*background:\s*var\(--c-surface-2\)/);
  });

  it('lets the dock wrap at the floor instead of overflowing', () => {
    expect(narrow).toMatch(/\.dock\s*\{[^}]*flex-wrap:\s*wrap/);
  });
});

describe('R-2 reflow rules', () => {
  it('gives the stat row a floor wide enough for its labels', () => {
    const match = /\.stats\s*\{[^}]*minmax\((\d+)px/.exec(css);
    expect(match).not.toBeNull();
    expect(Number(match?.[1])).toBeGreaterThanOrEqual(160);
  });

  it('lets tables scroll themselves rather than the page', () => {
    expect(css).toMatch(/\.table-wrap\s*\{[^}]*overflow:\s*auto/);
    // The content column must be allowed to shrink, or the table widens it
    // and the page scrolls horizontally instead.
    expect(css).toMatch(/\.content\s*\{[^}]*min-width:\s*0/);
  });

  it('truncates the header title rather than colliding with the status', () => {
    expect(css).toMatch(/\.header__title\s*\{[^}]*text-overflow:\s*ellipsis/);
    expect(css).toMatch(/\.header__actions\s*\{[^}]*flex:\s*none/);
  });
});
