/**
 * Tests for which renderer the shell loads (#123).
 *
 * Pure and Electron-free, so it runs in CI where the app is never loaded.
 * The behaviour it pins is the one that makes every SR-4 boot possible: an
 * unpackaged checkout can load the *built* renderer, under the production
 * CSP, without a signed package.
 */
import { describe, expect, it } from 'vitest';
import { pathToFileURL } from 'node:url';
import { DEV_SERVER_ORIGIN, resolveRendererSource } from '../electron/renderer-source.js';

const DIST = '/repo/desktop/dist/renderer/index.html';

describe('resolveRendererSource', () => {
  it('uses the Vite dev server for an unpackaged run with no override', () => {
    const source = resolveRendererSource({
      isPackaged: false,
      overrideUrl: undefined,
      distRendererPath: DIST,
    });
    expect(source.url).toBe(DEV_SERVER_ORIGIN);
    expect(source.devServer).toBe(true);
  });

  it('uses the built renderer beside the main process when packaged', () => {
    const source = resolveRendererSource({
      isPackaged: true,
      overrideUrl: undefined,
      distRendererPath: DIST,
    });
    expect(source.url).toBe(pathToFileURL(DIST).href);
    expect(source.devServer).toBe(false);
  });

  it('lets FERRY_RENDERER_URL point a checkout at the built renderer (#123)', () => {
    const built = pathToFileURL(DIST).href;
    const source = resolveRendererSource({
      isPackaged: false,
      overrideUrl: built,
      distRendererPath: DIST,
    });
    expect(source.url).toBe(built);
    // Not the dev server, so the production CSP applies — that is the point.
    expect(source.devServer).toBe(false);
  });

  it('treats an override to the dev server (any trailing slash) as dev', () => {
    const source = resolveRendererSource({
      isPackaged: false,
      overrideUrl: `${DEV_SERVER_ORIGIN}/`,
      distRendererPath: DIST,
    });
    expect(source.devServer).toBe(true);
  });

  it('ignores the override once packaged, so a shipped app cannot be redirected', () => {
    const source = resolveRendererSource({
      isPackaged: true,
      overrideUrl: 'http://elsewhere.example/index.html',
      distRendererPath: DIST,
    });
    expect(source.url).toBe(pathToFileURL(DIST).href);
    expect(source.devServer).toBe(false);
  });

  it('ignores a blank override', () => {
    const source = resolveRendererSource({
      isPackaged: true,
      overrideUrl: '   ',
      distRendererPath: DIST,
    });
    expect(source.url).toBe(pathToFileURL(DIST).href);
  });

  it('percent-encodes spaces, so a built path with one still loads', () => {
    const withSpace = '/Users/a b/desktop/dist/renderer/index.html';
    const source = resolveRendererSource({
      isPackaged: true,
      overrideUrl: undefined,
      distRendererPath: withSpace,
    });
    expect(source.url).toBe(pathToFileURL(withSpace).href);
    expect(source.url).toContain('a%20b');
  });

  it('does not treat a malformed override as the dev server', () => {
    const source = resolveRendererSource({
      isPackaged: false,
      overrideUrl: 'not a url',
      distRendererPath: DIST,
    });
    expect(source.devServer).toBe(false);
  });
});
