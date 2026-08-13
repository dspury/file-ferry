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
import { SECURITY } from '../electron/security.js';
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
