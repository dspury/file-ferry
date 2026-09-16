/**
 * `electron/main.ts` is an ES module (#138): `__dirname` and `require()` do
 * not exist there.
 *
 * The desktop CI job never loads Electron, so a `ReferenceError` at window
 * creation is invisible to the suite — which is exactly how the B-1 (#176) +
 * B-2 (#138) merge shipped `pathResolve(__dirname, …)` into the ESM main and
 * broke startup until it was caught by booting. This pins the constraint
 * statically, over the code with comments stripped so a prose mention does
 * not trip it.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(join(import.meta.dirname, '..', 'electron', 'main.ts'), 'utf8');
const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');

describe('electron/main.ts is an ES module', () => {
  it('does not reference __dirname in code', () => {
    expect(code).not.toMatch(/\b__dirname\b/);
  });

  it('does not call require() in code', () => {
    expect(code).not.toMatch(/\brequire\s*\(/);
  });
});
