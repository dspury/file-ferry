/**
 * Package 6 (B2) contract tests: the P2–P5 engine — destinations,
 * preset revisions, inventories, transfer plans/preflight/execution —
 * must be reachable through the preload bridge. The sidecar side is
 * covered by `tests/test_transfer_runner_e2e.py`; the typed catalog in
 * `shared/ipc-methods.ts` was completed in P5 and is unchanged here.
 */
import { describe, expect, it } from 'vitest';
import { api } from '../shared/preload-api.js';

describe('Package 6 IPC surface', () => {
  it('exposes the destination family', () => {
    expect(api.destination.save).toBeTypeOf('function');
    expect(api.destination.list).toBeTypeOf('function');
    expect(api.destination.get).toBeTypeOf('function');
    expect(api.destination.archive).toBeTypeOf('function');
    expect(api.destination.resolve).toBeTypeOf('function');
    expect(api.destination.discovery).toBeTypeOf('function');
    expect(api.destination.confirmBinding).toBeTypeOf('function');
  });

  it('exposes the inventory family', () => {
    expect(api.inventory.create).toBeTypeOf('function');
    expect(api.inventory.status).toBeTypeOf('function');
    expect(api.inventory.entries).toBeTypeOf('function');
  });

  it('exposes the transfer family, including start', () => {
    // The B2 acceptance: `window.ferry.transfer.start` must exist — this
    // is the method that turns an approved plan into a durable execution.
    expect(api.transfer.start).toBeTypeOf('function');
    expect(api.transfer.planCreate).toBeTypeOf('function');
    expect(api.transfer.planGet).toBeTypeOf('function');
    expect(api.transfer.planEntries).toBeTypeOf('function');
    expect(api.transfer.planResolve).toBeTypeOf('function');
    expect(api.transfer.planApprove).toBeTypeOf('function');
    expect(api.transfer.preflightStart).toBeTypeOf('function');
    expect(api.transfer.preflightStatus).toBeTypeOf('function');
    expect(api.transfer.receipt).toBeTypeOf('function');
    expect(api.transfer.receiptExport).toBeTypeOf('function');
  });

  it('exposes the preset-revision family on profile', () => {
    expect(api.profile.saveRevision).toBeTypeOf('function');
    expect(api.profile.listRevisions).toBeTypeOf('function');
    expect(api.profile.getRevision).toBeTypeOf('function');
    expect(api.profile.export).toBeTypeOf('function');
    expect(api.profile.import).toBeTypeOf('function');
  });

  it('the bridge namespace list includes destination, inventory, transfer', () => {
    const groups = Object.keys(api);
    for (const name of ['destination', 'inventory', 'transfer']) {
      expect(groups).toContain(name);
    }
  });

  it('keeps the new namespaces free of node/fs', () => {
    for (const ns of [api.destination, api.inventory, api.transfer]) {
      const flat = JSON.stringify(ns);
      expect(flat).not.toContain('require(');
      expect(flat).not.toContain('process.');
      expect(flat).not.toContain('fs.');
    }
  });
});
