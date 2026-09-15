/**
 * Which renderer the shell loads, and under which CSP (#123).
 *
 * The source used to be `app.isPackaged` alone, so `electron .` from a
 * checkout always hit the Vite dev server and failed hard without it. That
 * made a production-shaped renderer reachable only through a signed
 * `electron-builder` package, so the built path went unverified — the gap
 * #95 and the desktop verification work kept running into.
 *
 * `FERRY_RENDERER_URL` now overrides the source (mirroring `FERRY_PYTHON` for
 * the sidecar interpreter), so a checkout can boot the built renderer:
 *
 *   FERRY_RENDERER_URL=file:///…/dist/renderer/index.html electron .
 *   (or `npm run start:built`).
 *
 * The CSP follows the *source*, not `app.isPackaged`: the built renderer runs
 * under the production policy even from a checkout, because loading it under
 * the relaxed development policy would verify less than it appears to
 * (ADR-0006: the two paths differ by design).
 */
import { pathToFileURL } from 'node:url';

/** The Vite dev server `npm run dev` serves — the only source needing the
 *  development CSP. Matched by origin so a trailing slash still counts. */
export const DEV_SERVER_ORIGIN = 'http://localhost:5173';

export interface RendererSource {
  /** The URL the shell loads. */
  readonly url: string;
  /** True when the source is the Vite dev server, which needs the relaxed
   *  development CSP; false means the production policy. */
  readonly devServer: boolean;
}

function isDevServer(url: string): boolean {
  try {
    return new URL(url).origin === DEV_SERVER_ORIGIN;
  } catch {
    // A malformed override is not the dev server; it fails loudly at load.
    return false;
  }
}

/**
 * Pick the renderer source.
 *
 * `FERRY_RENDERER_URL` wins when set (blank/whitespace ignored). Otherwise an
 * unpackaged run uses the Vite dev server, and a packaged run uses the built
 * renderer beside the compiled main process (`dist/renderer/index.html`).
 */
export function resolveRendererSource(options: {
  readonly isPackaged: boolean;
  readonly overrideUrl: string | undefined;
  readonly distRendererPath: string;
}): RendererSource {
  const override = options.overrideUrl?.trim();
  const url =
    override !== undefined && override !== ''
      ? override
      : options.isPackaged
        ? pathToFileURL(options.distRendererPath).href
        : DEV_SERVER_ORIGIN;
  return { url, devServer: isDevServer(url) };
}
