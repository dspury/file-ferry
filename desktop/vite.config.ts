import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

/**
 * Relax the page's `<meta>` CSP while Vite is serving.
 *
 * `renderer/index.html` ships the production policy, which forbids inline
 * scripts. Vite's React plugin injects its refresh preamble inline, and CSP
 * composes (meta AND header must both allow), so without this the dev window
 * renders nothing: "@vitejs/plugin-react can't detect preamble".
 *
 * `apply: 'serve'` keeps this out of `vite build` -- the packaged page is
 * emitted with the strict policy untouched. The matching header relaxation
 * lives in `electron/security.ts` (DEVELOPMENT_CSP).
 */
function devCspPlugin(): Plugin {
  const devPolicy = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self' ws://localhost:5173 http://localhost:5173",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join('; ');
  return {
    name: 'ferry-dev-csp',
    apply: 'serve',
    transformIndexHtml(html) {
      // Prettier wraps the <meta> attributes onto separate lines, so match
      // across whitespace rather than assuming a single-line tag.
      return html.replace(
        /(http-equiv="Content-Security-Policy"\s+content=")[^"]*(")/,
        `$1${devPolicy}$2`,
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), devCspPlugin()],
  root: resolve(__dirname, 'renderer'),
  base: './',
  build: {
    outDir: resolve(__dirname, 'dist/renderer'),
    emptyOutDir: true,
    target: 'chrome120',
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
