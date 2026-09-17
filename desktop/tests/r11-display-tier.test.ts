/**
 * R-11: the SR-9 display numeral is not monospace.
 *
 * `.stat__value` rendered IBM Plex Mono at 64px, which read as a terminal
 * rather than the reference. SR-8 keeps mono for paths, byte counts,
 * durations, hashes and ids; the display tier is none of those. This pins the
 * face and the heavy weight, and keeps the tabular figures the old treatment
 * was defended with.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(
  join(import.meta.dirname, '..', 'renderer', 'src', 'styles.css'),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '');

const block = /\.stat__value\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';

describe('R-11 display numeral', () => {
  it('is set in the sans display face, not mono', () => {
    expect(block).toContain('font-family: var(--ff-sans)');
    expect(block).not.toContain('font-family: var(--ff-mono)');
  });

  it('uses a heavy weight', () => {
    const weight = Number(/font-weight:\s*(\d+)/.exec(block)?.[1]);
    expect(weight).toBeGreaterThanOrEqual(700);
  });

  it('keeps tabular figures for a future column', () => {
    expect(block).toContain('font-variant-numeric: tabular-nums');
  });

  it('is the only --fs-display consumer on the sheet', () => {
    const consumers = css.match(/var\(--fs-display\)/g) ?? [];
    expect(consumers).toHaveLength(1);
  });
});
