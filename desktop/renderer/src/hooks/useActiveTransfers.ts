/**
 * The shell's view of work in flight, for the transfer dock (R-4).
 *
 * Reads the job log once and then follows it over `job.updated`, the same way
 * Activity does, so the dock's state is the engine's, not a copy the screen
 * has to be open to refresh. Cancel is `job.cancel` — the Transfer
 * workspace's execution panel uses the same call, so the dock is not a
 * privileged path to a destructive action.
 */
import { useState } from 'react';
import { useAsync } from './useAsync.js';
import { useJobStream } from './useJobStream.js';
import { activeTransfers, TRANSFER_COMMAND } from '../lib/dock.js';
import type { JobDetail, JobSnapshot } from '../../../shared/ipc-methods.js';

export interface ActiveTransfers {
  /** The leading in-flight transfer, or null when nothing is running. */
  readonly job: JobDetail | null;
  /** Its latest live snapshot, or null before one has arrived. */
  readonly snapshot: JobSnapshot | null;
  /** How many other transfers are in flight behind the leading one. */
  readonly more: number;
  readonly cancelling: boolean;
  readonly error: string | null;
  readonly cancel: () => void;
}

export function useActiveTransfers(): ActiveTransfers {
  const jobs = useAsync(() => window.ferry.job.list());
  const raw = jobs.data?.jobs ?? [];
  // Only transfer jobs hold a subscription; a proxy or verify job does not
  // belong in the dock and does not need its events forwarded for this.
  const stream = useJobStream(
    raw.filter((job) => job.command === TRANSFER_COMMAND),
    jobs.reload,
  );
  const active = activeTransfers(raw, stream.snapshots);
  const job = active[0] ?? null;

  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cancel = (): void => {
    if (job === null) return;
    setCancelling(true);
    setError(null);
    window.ferry.job
      .cancel(job.id)
      .then(() => jobs.reload())
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)))
      .finally(() => setCancelling(false));
  };

  return {
    job,
    snapshot: job === null ? null : (stream.snapshots.get(job.id) ?? null),
    more: Math.max(0, active.length - 1),
    cancelling,
    error,
    cancel,
  };
}
