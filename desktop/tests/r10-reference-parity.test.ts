/**
 * R-10 reference parity — textual guards over `styles.css`.
 *
 * R-7 was reviewed by reading the diff and four gaps still reached the built
 * app. These tests pin the four decisions so the next pass cannot quietly
 * undo one: the active stage tab is a filled accent pill and the Transfer
 * view's one emitter (R-10a), no hovered row grows an edge mark (R-10b),
 * uppercase survives only in the nine micro-label rules (R-10c), and a
 * settled meter is muted, not green (R-10d).
 *
 * jsdom never applies the stylesheet, so — like `edge-bars.test.ts` — this
 * reads the file. Comments are stripped first so prose about a rule cannot
 * satisfy or fail an assertion.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const raw = readFileSync(join(import.meta.dirname, '..', 'renderer', 'src', 'styles.css'), 'utf8');
const css = raw.replace(/\/\*[\s\S]*?\*\//g, '');

/** The declaration block for a selector, match failure returning null. */
function block(selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match?.[1] ?? null;
}

describe('R-10a active stage tab', () => {
  it('is a solid interactive-accent fill with on-accent text', () => {
    const active = block('.tabs__item--active');
    expect(active).not.toBeNull();
    expect(active).toContain('background: var(--c-accent-interactive)');
    expect(active).toContain('color: var(--c-on-accent)');
  });

  it('no longer draws the inset underline the reference did not show', () => {
    expect(block('.tabs__item--active')).not.toContain('inset 0 -2px');
    expect(css).not.toMatch(/\.tabs__item--active[^{}]*\{[^}]*inset 0 -2px/);
  });

  it('scopes the glow budget to one emitter while the tabs are mounted', () => {
    expect(block('.tabs__item--active')).toContain('box-shadow: var(--glow-accent)');
    expect(block('.app:has(.tabs) .dock .progress__fill')).toContain('box-shadow: none');
  });
});

describe('R-10b no edge mark on a hovered row', () => {
  it('removes the inset left-edge tick from the hovered row', () => {
    expect(css).not.toMatch(/tr:hover[^{}]*\{[^}]*box-shadow/);
  });

  it('keeps the row background change, which is the affordance', () => {
    expect(block('.table tbody tr:hover td')).toContain('background: var(--c-surface-2)');
  });
});

describe('R-10c casing', () => {
  const DROPPED = [
    '.nav__wordmark',
    '.nav__tagline',
    '.card__title',
    '.tabs__item',
    '.seg__item',
    '.chip',
    '.progress-cell__note',
    '.confirm__title',
  ];

  it('drops uppercase from all eight non-micro-label rules', () => {
    for (const selector of DROPPED) {
      expect(block(selector), selector).not.toContain('text-transform: uppercase');
    }
  });

  it('drops the label tracking with the transform', () => {
    for (const selector of ['.tabs__item', '.chip', '.progress-cell__note']) {
      expect(block(selector), selector).not.toContain('letter-spacing');
    }
  });

  it('leaves uppercase in exactly the nine micro-label rules', () => {
    const count = (css.match(/text-transform: uppercase/g) ?? []).length;
    expect(count).toBe(9);
  });

  it('title-cases the segmented filter, whose enum values are lowercase', () => {
    expect(block('.seg__item')).toContain('text-transform: capitalize');
  });
});

describe('R-10d a settled meter is muted', () => {
  it('does not paint a complete bar in the success hue', () => {
    const complete = block('.progress--complete .progress__fill');
    expect(complete).not.toBeNull();
    expect(complete).not.toContain('background: var(--c-ok)');
    expect(complete).toContain('background: var(--c-text-faint)');
  });

  it('keeps the chip green — the state is the chip’s, not the bar’s', () => {
    expect(block('.chip--ok')).toContain('color: var(--c-ok)');
  });
});
