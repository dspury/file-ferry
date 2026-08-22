/**
 * Package 7a contract tests: the new IPC methods added for the desktop
 * screens (plan §8.3) must exist in the shared TS catalog and be
 * reachable through the preload API surface. The matching Python models
 * live in `service/protocol.py` and are covered by test_service_wiring.
 */
import { describe, expect, it } from 'vitest';
import { api } from '../shared/preload-api.js';

describe('Package 7 IPC surface', () => {
  it('exposes the settings family', () => {
    expect(api.settings.get).toBeTypeOf('function');
    expect(api.settings.update).toBeTypeOf('function');
  });

  it('exposes the doctor surface', () => {
    expect(api.app.doctor).toBeTypeOf('function');
  });

  it('exposes job resume/retry', () => {
    expect(api.job.resume).toBeTypeOf('function');
    expect(api.job.retry).toBeTypeOf('function');
  });

  it('exposes profile.preview and receipt.get', () => {
    expect(api.profile.preview).toBeTypeOf('function');
    expect(api.receipt.get).toBeTypeOf('function');
  });

  it('keeps the settings namespace narrow (only get/update)', () => {
    expect(Object.keys(api.settings).sort()).toEqual(['get', 'update']);
  });

  it('does not leak node/fs through the settings surface', () => {
    const flat = JSON.stringify(api.settings);
    expect(flat).not.toContain('require(');
    expect(flat).not.toContain('process.');
    expect(flat).not.toContain('fs.');
  });
});
