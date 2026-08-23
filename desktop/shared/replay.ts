/**
 * Renderer reconnect replay.
 *
 * A renderer reload or crash may lose its live job subscription, but it
 * must not lose job state (ADR-0001, plan §5.1). Electron main keeps the
 * latest known snapshot per subscribed job and replays it to a window on
 * (re)connect. This module is the pure store behind that behaviour so it
 * is testable without Electron.
 */

import type { JobSnapshot, JobEvent } from './ipc-methods.js';
import type { EventFrame } from './ipc-schema.js';
import { PROTOCOL_VERSION } from './version.js';

/**
 * Bounded store of the latest job snapshots keyed by job id.
 *
 * ``record`` keeps the newest snapshot for a job; ``snapshotFor`` returns
 * the latest known state or null if never seen. The store is bounded to
 * guard against an unbounded number of historical jobs being replayed to
 * a freshly reloaded window.
 */
/**
 * Narrow a `job.updated` event payload to the snapshot it carries.
 *
 * The frame arrives off the wire, so its params are untyped. This checks
 * the shape rather than asserting it: the previous call site cast the frame
 * to a hand-written shape and passed the snapshot through `as never`, which
 * silenced the compiler no matter what the sidecar actually sent. The
 * accepted condition is the one that code tested — an object carrying a
 * snapshot whose `id` is a non-empty string.
 */
export function isJobUpdatedParams(params: EventFrame['params']): params is JobEvent {
  if (typeof params !== 'object' || params === null) return false;
  if (!('snapshot' in params)) return false;
  const snapshot = params.snapshot;
  if (typeof snapshot !== 'object' || snapshot === null) return false;
  return 'id' in snapshot && typeof snapshot.id === 'string' && snapshot.id.length > 0;
}

/**
 * Build the `job.updated` frame for a snapshot.
 *
 * The reconnect replay used to post a bare `{ jobId, snapshot }` object on
 * the same channel the live forward puts a full `EventFrame` on, so a
 * renderer listener typed against `EventFrame` saw two different shapes and
 * `frame.params` was undefined for every replayed job. Both paths go
 * through this now, so there is one shape to handle.
 */
export function jobUpdatedFrame(snapshot: JobSnapshot): EventFrame<JobEvent> {
  return {
    jsonrpc: '2.0',
    v: PROTOCOL_VERSION,
    kind: 'event',
    method: 'job.updated',
    params: { jobId: snapshot.id, snapshot },
  };
}

export class JobSnapshotStore {
  private readonly snapshots: Map<string, JobSnapshot>;
  private readonly maxEntries: number;

  constructor(maxEntries = 500) {
    this.snapshots = new Map();
    this.maxEntries = maxEntries;
  }

  record(snapshot: JobSnapshot): void {
    this.snapshots.set(snapshot.id, snapshot);
    // Evict oldest beyond the bound (Map preserves insertion order).
    while (this.snapshots.size > this.maxEntries) {
      const first = this.snapshots.keys().next().value;
      if (first === undefined) break;
      this.snapshots.delete(first);
    }
  }

  snapshotFor(jobId: string): JobSnapshot | null {
    return this.snapshots.get(jobId) ?? null;
  }

  /** All known snapshots, most-recently-recorded first. */
  all(): JobSnapshot[] {
    return [...this.snapshots.values()];
  }

  clear(): void {
    this.snapshots.clear();
  }
}

/**
 * Build the snapshot payload to replay to a freshly connected window.
 * Returns the snapshots in stable order (recency-descending).
 */
export function replayPayload(store: JobSnapshotStore): JobSnapshot[] {
  return store.all().reverse();
}
