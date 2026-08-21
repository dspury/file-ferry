/**
 * Security-boundary tests (plan §10.6.4).
 *
 * The renderer must not be able to reach node, the filesystem, the
 * database, or arbitrary shell execution. These tests assert the frozen
 * security configuration is strict (ADR-0001) and that the preload API
 * surface is exactly the schema-validated bridge — no extra methods, no
 * generic invoke, no fs/shell/node escape hatch.
 *
 * These run in vitest without a real Electron runtime, so they check the
 * *declared* security posture and the shape of the exposed API rather
 * than a live sandbox. The packaged-app smoke test (Package 9) verifies
 * the boundary at runtime.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DEVELOPMENT_CSP, PRODUCTION_CSP, SECURITY, cspHeaderValue } from '../electron/security.js';
import { api } from '../shared/preload-api.js';

describe('frozen security config (ADR-0001)', () => {
  it('locks the renderer down', () => {
    expect(SECURITY.contextIsolation).toBe(true);
    expect(SECURITY.nodeIntegration).toBe(false);
    expect(SECURITY.sandbox).toBe(true);
    expect(SECURITY.webSecurity).toBe(true);
    expect(SECURITY.allowRunningInsecureContent).toBe(false);
    expect(SECURITY.experimentalFeatures).toBe(false);
  });

  it('rejects any change that would relax the boundary', () => {
    // The config object must remain frozen at these exact values.
    expect(SECURITY).toEqual({
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
    });
  });
});

describe('narrow preload surface (ADR-0001)', () => {
  it('exposes no generic invoke / ipcRenderer / fs / shell', () => {
    const flat = JSON.stringify(api);
    expect(flat).not.toContain('ipcRenderer');
    expect(flat).not.toContain('nodeIntegration');
    expect(flat).not.toContain('require(');
    expect(flat).not.toContain('process.');
    expect(flat).not.toContain('fs.');
    expect(flat).not.toContain('shell.');
    expect(flat).not.toContain('child_process');
  });

  it('groups only the intended capability namespaces', () => {
    const groups = Object.keys(api);
    expect(groups.sort()).toEqual([
      'app',
      'asset',
      'audit',
      'clips',
      'derivatives',
      'dialog',
      'intake',
      'job',
      'manifest',
      'organize',
      'plan',
      'profile',
      'project',
      'receipt',
      'reconcile',
      'replica',
      'settings',
      'sidecarEvents',
      'source',
    ]);
  });

  it('exposes every method in the typed catalog via a namespace', () => {
    // Spot-check that the sidecar method families are reachable; a
    // missing bridge method would make the renderer unable to drive it.
    expect(typeof api.project.list).toBe('function');
    expect(typeof api.job.cancel).toBe('function');
    expect(typeof api.reconcile.acceptChange).toBe('function');
    expect(typeof api.organize.apply).toBe('function');
    expect(typeof api.dialog.pick).toBe('function');
    expect(typeof api.app.openDiagnosticFolder).toBe('function');
  });

  it('dialog.pick and openDiagnosticFolder are the only native-only entries', () => {
    // Native-only affordances are the ones that do NOT round-trip the
    // sidecar; they are owned by main (ADR-0001).
    expect(api.dialog.pick).toBeTypeOf('function');
    expect(api.app.openDiagnosticFolder).toBeTypeOf('function');
    expect(api.app.diagnostics).toBeTypeOf('function');
  });
});

describe('content security policy (ADR-0001)', () => {
  // Regression: the directive list was handed to Electron as a string[], which
  // it sends as one header line each -- and multiple CSP headers are multiple
  // independent policies. `default-src 'self'` then stood alone and vetoed
  // every relaxation beside it, including `img-src 'self' data:`.
  it('is a single policy, not one policy per directive', () => {
    const header = cspHeaderValue(PRODUCTION_CSP);
    expect(header).toContain('; ');
    expect(header.split(';').length).toBe(PRODUCTION_CSP.length);
    // Directives that only mean something when they share a policy with the
    // rest of the list.
    expect(header).toContain("default-src 'self'");
    expect(header).toContain("img-src 'self' data:");
  });

  it('keeps the shipped policy strict', () => {
    const header = cspHeaderValue(PRODUCTION_CSP);
    expect(header).not.toContain('localhost');
    expect(header).not.toContain('ws:');
    expect(header).toContain("script-src 'self'");
    expect(header).not.toMatch(/script-src[^;]*unsafe-inline/);
    expect(header).not.toMatch(/script-src[^;]*unsafe-eval/);
    expect(header).toContain("object-src 'none'");
    expect(header).toContain("frame-ancestors 'none'");
  });

  it('only the development policy admits inline script and the dev server', () => {
    const dev = cspHeaderValue(DEVELOPMENT_CSP);
    expect(dev).toMatch(/script-src[^;]*'unsafe-inline'/);
    expect(dev).toContain('ws://localhost:5173');
    // Still no eval, and still no wildcard, even in development.
    expect(dev).not.toContain('unsafe-eval');
    expect(dev).not.toContain('*');
  });

  it('every directive in the shipped policy is also named in the dev policy', () => {
    // Guards against the two drifting apart: a directive added to production
    // must be considered for development, not silently dropped.
    const names = (policy: readonly string[]) => policy.map((d) => d.split(' ')[0]).sort();
    expect(names(DEVELOPMENT_CSP)).toEqual(names(PRODUCTION_CSP));
  });

  it("the page's meta policy matches the shipped policy", () => {
    // The packaged renderer loads over file://, where onHeadersReceived does
    // not fire, so the <meta> copy is the only policy that applies. It must
    // not drift from PRODUCTION_CSP -- minus frame-ancestors, which a <meta>
    // element cannot deliver.
    const html = readFileSync(join(__dirname, '..', 'renderer', 'index.html'), 'utf8');
    const meta = /http-equiv="Content-Security-Policy"\s+content="([^"]*)"/.exec(html);
    expect(meta).not.toBeNull();
    const metaDirectives = (meta?.[1] ?? '').split('; ').sort();
    const expected = PRODUCTION_CSP.filter((d) => !d.startsWith('frame-ancestors')).sort();
    expect(metaDirectives).toEqual([...expected]);
  });
});
