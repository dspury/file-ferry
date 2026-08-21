/**
 * Frozen security configuration for the Electron main process.
 * See ADR-0001.
 *
 * The settings here are the security boundary. Any change that
 * relaxes them requires a new ADR.
 */
import type { BrowserWindowConstructorOptions, Session } from 'electron';

export interface SecurityConfig {
  readonly contextIsolation: true;
  readonly nodeIntegration: false;
  readonly sandbox: true;
  readonly webSecurity: true;
  readonly allowRunningInsecureContent: false;
  readonly experimentalFeatures: false;
}

export const SECURITY: SecurityConfig = {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  experimentalFeatures: false,
};

/**
 * The BrowserWindow options that are derived from the security
 * policy. The renderer-facing options MUST use these; the only
 * items that vary per window are position, size, and parent.
 */
export function baseWindowOptions(): BrowserWindowConstructorOptions {
  return {
    ...SECURITY,
    show: false,
    backgroundColor: '#0d0f14',
  };
}

/**
 * The shipped Content-Security-Policy. The renderer has no need for
 * cross-origin fetches; the allowlist is local. This is the policy every
 * packaged build runs under, and relaxing it requires a new ADR.
 *
 * The packaged renderer loads over `file://`, where `onHeadersReceived` does
 * not fire, so `renderer/index.html` carries the same policy in a `<meta>`
 * element. Both must stay in step. (`frame-ancestors` is header-only — a
 * `<meta>` copy of it is ignored by the browser — so it lives here alone.)
 */
export const PRODUCTION_CSP: readonly string[] = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
];

/**
 * Development-only policy, used when the renderer is served by Vite.
 *
 * Vite's React plugin installs its refresh preamble as an inline script and
 * talks to the dev server over a websocket; the production policy blocks both,
 * which left `npm run dev` rendering an empty window. This is reachable only
 * while `app.isPackaged` is false — see the call in `main.ts` — so it never
 * loosens a shipped build. `vite.config.ts` applies the matching relaxation to
 * the `<meta>` policy in serve mode, since CSP composes and the stricter of
 * the two would otherwise still win.
 */
export const DEVELOPMENT_CSP: readonly string[] = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self' ws://localhost:5173 http://localhost:5173",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
];

/**
 * Set the Content-Security-Policy on the session.
 *
 * @param isDev must mirror `!app.isPackaged`; a packaged build always gets
 *   {@link PRODUCTION_CSP}.
 */
export function applyContentSecurityPolicy(session: Session, isDev = false): void {
  const header = cspHeaderValue(isDev ? DEVELOPMENT_CSP : PRODUCTION_CSP);
  session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [header],
      },
    });
  });
}

/**
 * Join directives into one header value.
 *
 * Electron treats a `string[]` response header as *multiple header lines*, and
 * multiple `Content-Security-Policy` headers are multiple independent
 * policies, each enforced on its own. Passing the directive list straight
 * through therefore shipped ten one-directive policies: `default-src 'self'`
 * stood alone, so it vetoed `img-src 'self' data:` and every other relaxation,
 * while `script-src` was absent from that policy and fell back to `default-src`.
 * One policy per header, directives separated by `;`.
 */
export function cspHeaderValue(policy: readonly string[]): string {
  return policy.join('; ');
}
