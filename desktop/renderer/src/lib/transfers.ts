/**
 * Pure presentation logic for the transfer pipeline screens (P6/B3).
 *
 * Same discipline as `job-state.ts`: nothing here decides what the engine
 * *does* — the sidecar enforces the gates (approval needs a current passing
 * preflight; a moved fingerprint is refused; `needs_review` blocks). This
 * decides how a state the sidecar already reported is drawn, and it is the
 * one place the UI reasons about those gates, so the screens cannot drift
 * apart about what "startable" means.
 */
import type { JsonObject, JsonValue } from '../../../shared/ipc-schema.js';
import type { StateTone } from './job-state.js';

/**
 * The saved destination lives separately from whether it can be used right
 * now; `destination.resolve` reports the live half. Typed `string` on the
 * wire, so the default is load-bearing.
 */
export function destinationStatusTone(status: string): StateTone {
  switch (status) {
    case 'available':
      return 'ok';
    case 'offline':
      return 'neutral';
    case 'needs_confirmation':
    case 'ambiguous':
      return 'attention';
    case 'unwritable':
      return 'danger';
    default:
      return 'neutral';
  }
}

/** Inventory scan progress, drawn the way the job states are. */
export function inventoryStatusTone(status: string): StateTone {
  switch (status) {
    case 'scanning':
      return 'active';
    case 'complete':
      return 'ok';
    case 'failed':
      return 'danger';
    default:
      return 'neutral';
  }
}

/** Plan lifecycle, per `application/transfer_plan.py`. */
export function planStatusTone(status: string): StateTone {
  switch (status) {
    case 'draft':
      return 'neutral';
    case 'approved':
    case 'executing':
      return 'active';
    case 'executed':
      return 'ok';
    case 'invalidated':
      return 'attention';
    default:
      return 'neutral';
  }
}

/** Preflight outcome; `failed` is attention rather than danger — it refuses
 *  approval, it is not a destroyed transfer. */
export function preflightStatusTone(status: string): StateTone {
  switch (status) {
    case 'running':
      return 'active';
    case 'passed':
      return 'ok';
    case 'failed':
      return 'attention';
    default:
      return 'neutral';
  }
}

/** A transfer receipt's final state, keyed like the job states it wraps. */
export function receiptStateTone(finalState: string): StateTone {
  switch (finalState) {
    case 'succeeded':
      return 'ok';
    case 'cancelled':
      return 'cancelled';
    case 'needs_attention':
      return 'attention';
    case 'failed':
      return 'danger';
    default:
      return 'neutral';
  }
}

export interface StartGate {
  readonly canStart: boolean;
  /** Why start is disabled; shown as the button's tooltip and next to it. */
  readonly reason: string | null;
}

/**
 * The stale-approval guard, on the UI side as well as the server's (A08).
 *
 * Approval is for one exact plan substance, not a plan id: resolving
 * findings produces a *new* plan with a new fingerprint, and an approval
 * that briefly outlived the configuration it was granted against must
 * never reach the runner. The sidecar refuses a stale fingerprint too —
 * this gate exists so the button says so *before* the click, and so a
 * screen cannot render an enabled Start beside a plan the server would
 * bounce.
 */
export function startGate(plan: {
  readonly status: string;
  readonly fingerprint: string;
  readonly approvedFingerprint?: string | null;
}): StartGate {
  if (plan.status === 'executed') {
    return { canStart: false, reason: 'This plan has already been executed.' };
  }
  if (plan.status !== 'approved') {
    return { canStart: false, reason: 'Approve a passing preflight first.' };
  }
  if (plan.approvedFingerprint !== plan.fingerprint) {
    return {
      canStart: false,
      reason:
        'Approval is stale: the plan changed after it was approved. Review and approve again.',
    };
  }
  return { canStart: true, reason: null };
}

/**
 * Which plan entries a reviewer can still decide about. Resolved rounds
 * carry decisions forward, so a previously-decided entry shows its outcome
 * rather than offering the same decision twice.
 */
export function isDecisionPending(entry: {
  readonly action: string;
  readonly excludedByUser: boolean;
}): boolean {
  return (
    (entry.action === 'needs_review' || entry.action === 'skip_identical') && !entry.excludedByUser
  );
}

// ---- receipt reading ------------------------------------------------------
// The receipt arrives as the wire's `JsonObject` — its schema is pinned
// Python-side and asserted by the e2e suite; the TS side deliberately does
// not re-declare it. These readers narrow instead of casting: a receipt the
// sidecar did not write displays as "missing" rather than being trusted.

export interface ReceiptSummary {
  readonly committed: number | null;
  readonly failed: number | null;
  readonly expectedFiles: number | null;
  readonly bytesCommitted: number | null;
  readonly errors: readonly string[];
}

export interface ReceiptEntryRow {
  readonly state: string;
  readonly sourcePath: string;
  readonly destRelPath: string;
  readonly size: number | null;
  readonly warning: string | null;
  readonly error: string | null;
}

// The three guards below are the decode layer for a `JsonObject` receipt:
// each is a real type predicate, so the `typeof` checks inside them are the
// sanctioned place where wire values earn a domain type. Everything outside
// the guards branches on the decoded result.

function isRecord(value: JsonValue | undefined): value is { readonly [key: string]: JsonValue } {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNumber(value: JsonValue | undefined): value is number {
  return typeof value === 'number';
}

function isText(value: JsonValue | undefined): value is string {
  return typeof value === 'string';
}

function isTextList(value: JsonValue | undefined): value is string[] {
  return Array.isArray(value) && value.every(isText);
}

export function receiptSummary(receipt: JsonObject): ReceiptSummary {
  const actual = isRecord(receipt.actual) ? receipt.actual : null;
  const expected = isRecord(receipt.expected) ? receipt.expected : null;
  const errors = isTextList(receipt.errors) ? receipt.errors : [];
  return {
    committed: actual !== null && isNumber(actual.committed) ? actual.committed : null,
    failed: actual !== null && isNumber(actual.failed) ? actual.failed : null,
    expectedFiles: expected !== null && isNumber(expected.totalFiles) ? expected.totalFiles : null,
    bytesCommitted:
      actual !== null && isNumber(actual.bytesCommitted) ? actual.bytesCommitted : null,
    errors,
  };
}

/** The first `limit` receipt entries, plus how many there are in total. */
export interface ReceiptPage {
  readonly rows: readonly ReceiptEntryRow[];
  readonly total: number;
}

export function receiptEntries(receipt: JsonObject, limit = 200): ReceiptPage {
  if (!Array.isArray(receipt.entries)) return { rows: [], total: 0 };
  const rows: ReceiptEntryRow[] = [];
  for (const raw of receipt.entries.slice(0, limit)) {
    if (!isRecord(raw)) continue;
    rows.push({
      state: isText(raw.state) ? raw.state : 'unknown',
      sourcePath: isText(raw.sourcePath) ? raw.sourcePath : '—',
      destRelPath: isText(raw.destRelPath) ? raw.destRelPath : '—',
      size: isNumber(raw.size) ? raw.size : null,
      warning: isText(raw.warning) ? raw.warning : null,
      error: isText(raw.error) ? raw.error : null,
    });
  }
  return { rows, total: receipt.entries.length };
}
