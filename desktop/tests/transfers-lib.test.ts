/**
 * Pure transfer-pipeline presentation logic (P6/B3).
 *
 * The screens choose which primitive says what; these tests pin the
 * mappings and — most importantly — the start gate, which is the UI half
 * of the stale-approval rule (A08). The server refuses a stale fingerprint
 * too; the gate exists so the button says so before the click.
 */
import { describe, expect, it } from 'vitest';
import {
  destinationStatusTone,
  inventoryStatusTone,
  isDecisionPending,
  planStatusTone,
  preflightStatusTone,
  receiptEntries,
  receiptStateTone,
  receiptSummary,
  startGate,
} from '../renderer/src/lib/transfers.js';

describe('state -> chip tone', () => {
  it('maps the destination availability ladder', () => {
    expect(destinationStatusTone('available')).toBe('ok');
    expect(destinationStatusTone('offline')).toBe('neutral');
    expect(destinationStatusTone('needs_confirmation')).toBe('attention');
    expect(destinationStatusTone('ambiguous')).toBe('attention');
    expect(destinationStatusTone('unwritable')).toBe('danger');
    // Unknown states draw a quiet chip rather than blanking the table.
    expect(destinationStatusTone('something-new')).toBe('neutral');
  });

  it('maps plan, inventory, preflight, and receipt states', () => {
    expect(planStatusTone('draft')).toBe('neutral');
    expect(planStatusTone('approved')).toBe('active');
    expect(planStatusTone('executed')).toBe('ok');
    expect(planStatusTone('invalidated')).toBe('attention');

    expect(inventoryStatusTone('scanning')).toBe('active');
    expect(inventoryStatusTone('complete')).toBe('ok');
    expect(inventoryStatusTone('failed')).toBe('danger');

    expect(preflightStatusTone('running')).toBe('active');
    expect(preflightStatusTone('passed')).toBe('ok');
    expect(preflightStatusTone('failed')).toBe('attention');

    expect(receiptStateTone('succeeded')).toBe('ok');
    expect(receiptStateTone('cancelled')).toBe('cancelled');
    expect(receiptStateTone('needs_attention')).toBe('attention');
  });
});

describe('startGate (A08 on the UI side)', () => {
  it('refuses an unapproved plan', () => {
    const gate = startGate({ status: 'draft', fingerprint: 'f1', approvedFingerprint: null });
    expect(gate.canStart).toBe(false);
    expect(gate.reason).toContain('Approve');
  });

  it('allows an approved plan whose fingerprint still matches', () => {
    const gate = startGate({ status: 'approved', fingerprint: 'f1', approvedFingerprint: 'f1' });
    expect(gate.canStart).toBe(true);
    expect(gate.reason).toBeNull();
  });

  it('refuses an approval that outlived the plan it was granted against', () => {
    const gate = startGate({ status: 'approved', fingerprint: 'f2', approvedFingerprint: 'f1' });
    expect(gate.canStart).toBe(false);
    expect(gate.reason).toContain('stale');
  });

  it('refuses a plan that already ran', () => {
    const gate = startGate({ status: 'executed', fingerprint: 'f1', approvedFingerprint: 'f1' });
    expect(gate.canStart).toBe(false);
    expect(gate.reason).toContain('already');
  });
});

describe('isDecisionPending', () => {
  it('is true for findings a person has not decided about', () => {
    expect(isDecisionPending({ action: 'needs_review', excludedByUser: false })).toBe(true);
    expect(isDecisionPending({ action: 'skip_identical', excludedByUser: false })).toBe(true);
    expect(isDecisionPending({ action: 'needs_review', excludedByUser: true })).toBe(false);
    expect(isDecisionPending({ action: 'copy', excludedByUser: false })).toBe(false);
  });
});

describe('receipt reading (JsonObject, decoded not cast)', () => {
  it('reads the summary and reports missing fields as null', () => {
    const summary = receiptSummary({
      actual: { committed: 3, failed: 1, bytesCommitted: 42 },
      expected: { totalFiles: 4 },
      errors: ['a failure happened'],
    });
    expect(summary.committed).toBe(3);
    expect(summary.failed).toBe(1);
    expect(summary.expectedFiles).toBe(4);
    expect(summary.bytesCommitted).toBe(42);
    expect(summary.errors).toEqual(['a failure happened']);

    const empty = receiptSummary({});
    expect(empty.committed).toBeNull();
    expect(empty.expectedFiles).toBeNull();
    expect(empty.errors).toEqual([]);
  });

  it('pages entries and skips malformed ones without failing', () => {
    const receipt = {
      entries: [
        { state: 'committed', sourcePath: '/card/a', destRelPath: 'd/a', size: 12 },
        'not-an-entry',
        { state: 'failed', destRelPath: 'd/b', error: 'no space' },
      ],
    };
    const page = receiptEntries(receipt);
    expect(page.total).toBe(3);
    expect(page.rows).toHaveLength(2);
    expect(page.rows[0]).toEqual({
      state: 'committed',
      sourcePath: '/card/a',
      destRelPath: 'd/a',
      size: 12,
      warning: null,
      error: null,
    });
    expect(page.rows[1]!.error).toBe('no space');
  });

  it('caps the rows at the limit while reporting the whole count', () => {
    const entries = Array.from({ length: 5 }, (_, i) => ({
      state: 'committed',
      destRelPath: `f${i}`,
    }));
    const page = receiptEntries({ entries }, 3);
    expect(page.rows).toHaveLength(3);
    expect(page.total).toBe(5);
  });
});
