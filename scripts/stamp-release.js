#!/usr/bin/env node
/**
 * Stamp release provenance into shared/release.ts (plan §10 Pkg9 step 2).
 *
 * Reads MM_VERSION / MM_COMMIT / MM_BUILD_TIME / MM_ARCH env vars and
 * replaces the `getReleaseInfo()` fallback block with the concrete
 * values. Idempotent: running it again overwrites the stamp.
 *
 * The generated values are committed only for a release tag; dev builds
 * run with the `unknown` defaults.
 */
const fs = require('node:fs');
const path = require('node:path');

const file = path.resolve(__dirname, '..', 'desktop', 'shared', 'release.ts');
const env = process.env;
const info = {
  version: env.MM_VERSION || '0.0.0-dev',
  commit: env.MM_COMMIT || 'unknown',
  buildTime: env.MM_BUILD_TIME || new Date(0).toISOString(),
  arch: env.MM_ARCH || '',
  protocolVersion: 1,
};

let src = fs.readFileSync(file, 'utf8');
const start = src.indexOf('export function getReleaseInfo()');
const end = src.indexOf('}\n', start) + 2;
if (start === -1 || end <= start) {
  throw new Error('could not locate getReleaseInfo() in release.ts');
}
const block =
  'export function getReleaseInfo(): ReleaseInfo {\n' +
  '  if (override) return override;\n' +
  '  return ' +
  JSON.stringify(info, null, 2) +
  ';\n' +
  '}\n';
src = src.slice(0, start) + block + src.slice(end);
fs.writeFileSync(file, src);
console.log('stamped release.ts', JSON.stringify(info));
