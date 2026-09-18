/**
 * Pure transfer-dock logic (R-4), testable without React/DOM.
 *
 * The dock is the always-visible representation of work in flight. It reads
 * the job log rather than the Transfer route, so it survives navigating away;
 * this module decides which job leads, how far along it is, and how long is
 * left, so the component only draws.
 */
import { mergeJobSnapshot, snapshotProgress } from './activity.js';
import { formatBytes, formatCount } from './format.js';
import type { JobDetail, JobSnapshot } from '../../../shared/ipc-methods.js';

/** The durable transfer engine's job command. */
export const TRANSFER_COMMAND = 'transfer';

/**
 * A transfer is "in flight" while it is moving or about to: queued, running,
 * or verifying. A stalled job (`resumable`, `needs_attention`) is not moving,
 * so the dock clears for it — that job belongs to Activity and its receipt,
 * not to a bar that would sit at a fixed percentage forever.
 */
const DOCK_ACTIVE_STATES = new Set(['queued', 'running', 'verifying']);

/**
 * The active transfer jobs, most recently updated first.
 *
 * Snapshots are folded in first, so a job that settled over the event stream
 * leaves this list without waiting for a `job.list` reload — the dock cannot
 * keep claiming "running" after the run stopped.
 */
export function activeTransfers(
  jobs: readonly JobDetail[],
  snapshots: ReadonlyMap<string, JobSnapshot>,
): readonly JobDetail[] {
  return jobs
    .map((job) => mergeJobSnapshot(job, snapshots.get(job.id) ?? null))
    .filter((job) => job.command === TRANSFER_COMMAND && DOCK_ACTIVE_STATES.has(job.state))
    .sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0));
}

/**
 * The short job reference the dock shows in its title, and that its Cancel is
 * named with.
 *
 * The full id is a 36-character UUID; the Activity table names its row
 * controls with the whole thing because a table can hold many rows of the
 * same command and only the full id is guaranteed unique there. The dock
 * names exactly one leading transfer at a time, so the first 8 characters are
 * ample, and they are already what the title displays — the accessible name
 * and the visible reference agree.
 */
export function dockJobRef(job: JobDetail): string {
  return job.id.slice(0, 8);
}

/** The dock's state micro-label. */
export function dockStateLabel(state: string): string {
  switch (state) {
    case 'queued':
      return 'Queued';
    case 'running':
      return 'Transferring';
    case 'verifying':
      return 'Verifying';
    default:
      return state.replace(/_/g, ' ');
  }
}

/**
 * Seconds left, from the average byte rate so far — an estimate, and shown as
 * one. Null when it cannot be estimated: no total, no bytes yet, or no elapsed
 * time (all of which would otherwise divide by zero or claim "0s left").
 */
export function etaSeconds(snapshot: JobSnapshot | null): number | null {
  if (snapshot === null) return null;
  if (snapshot.totalBytes <= 0 || snapshot.bytesCopied <= 0) return null;
  const elapsed = (Date.parse(snapshot.updatedAt) - Date.parse(snapshot.startedAt)) / 1000;
  if (!(elapsed > 0)) return null;
  const rate = snapshot.bytesCopied / elapsed;
  if (!(rate > 0)) return null;
  const remaining = (snapshot.totalBytes - snapshot.bytesCopied) / rate;
  return remaining > 0 ? Math.round(remaining) : 0;
}

/** "4m 12s" / "1h 3m" / "45s". */
export function formatEta(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${s}s`;
}

/** The counter line: files, bytes, and time left — whichever are known. */
export function dockCounters(snapshot: JobSnapshot | null): string | null {
  if (snapshot === null) return null;
  const parts: string[] = [];
  if (snapshot.totalItems > 0) {
    parts.push(
      `${formatCount(snapshot.completedItems)} / ${formatCount(snapshot.totalItems)} files`,
    );
  }
  if (snapshot.totalBytes > 0) {
    parts.push(`${formatBytes(snapshot.bytesCopied)} of ${formatBytes(snapshot.totalBytes)}`);
  }
  const eta = etaSeconds(snapshot);
  if (eta !== null) parts.push(`${formatEta(eta)} left`);
  return parts.length > 0 ? parts.join(' · ') : null;
}

/** The meter's 0..100, from the live snapshot. */
export function dockPercent(snapshot: JobSnapshot | null): number {
  return snapshot === null ? 0 : Math.round(snapshotProgress(snapshot) * 100);
}
