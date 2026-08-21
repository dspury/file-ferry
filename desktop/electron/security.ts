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
 * Set a strict Content-Security-Policy on the session. The renderer
 * has no need for cross-origin fetches; the allowlist is local.
 */
export function applyContentSecurityPolicy(session: Session): void {
  session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
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
        ],
      },
    });
  });
}
