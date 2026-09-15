#!/usr/bin/env node
/**
 * Boot the *built* renderer from a checkout, without packaging (#123).
 *
 * `npm run dev` runs the Vite dev server, and bare `electron .` expects it.
 * This sets `FERRY_RENDERER_URL` to `dist/renderer/index.html` and launches
 * Electron, so the production-shaped renderer (minified, `file://`, the
 * production CSP) can be run and verified without Apple credentials.
 *
 * `npm run start:built` builds first, then runs this.
 */
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import electronPath from 'electron';

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const indexHtml = resolve(desktopRoot, 'dist', 'renderer', 'index.html');

const child = spawn(electronPath, ['.'], {
  cwd: desktopRoot,
  stdio: 'inherit',
  env: { ...process.env, FERRY_RENDERER_URL: pathToFileURL(indexHtml).href },
});
child.on('exit', (code, signal) => {
  process.exit(signal === null ? (code ?? 0) : 1);
});
