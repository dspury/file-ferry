/**
 * Renderer reconnect replay.
 *
 * A renderer reload or crash may lose its live job subscription, but it
 * must not lose job state (ADR-0001, plan §5.1). Electron main keeps the
 * latest known snapshot per subscribed job and replays it to a window on
 * (re)connect. This module is the pure store behind that behaviour so it
 * is testable without Electron.
 */

import type { JobSnapshot } from './ipc-methods.js';

/**
 * Bounded store of the latest job snapshots keyed by job id.
 *
 * ``record`` keeps the newest snapshot for a job; ``snapshotFor`` returns
 * the latest known state or null if never seen. The store is bounded to
 * guard against an unbounded number of historical jobs being replayed to
 * a freshly reloaded window.
 */
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
      const first = this.snapshots.keys().next().value as string | undefined;
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
