/**
 * The persistent transfer dock (R-4).
 *
 * Presentational: `useActiveTransfers` owns the data and the cancel call, so
 * the dock has no privileged path to a destructive action — its Cancel is the
 * same `job.cancel` the Transfer workspace's execution panel calls, and it is
 * only offered while the job is cancellable.
 *
 * The identity line names the job the engine reported. `JobDetail` carries no
 * source/destination labels, so this shows the command and a short id; real
 * labels need a job -> plan read on the engine, which does not exist yet.
 */
import type { JSX } from 'react';
import { Progress } from './ui.js';
import { IconTransfer } from './icons.js';
import { jobMeterStatus } from '../lib/job-state.js';
import { jobLabel } from '../lib/activity.js';
import { dockCounters, dockPercent, dockJobRef, dockStateLabel } from '../lib/dock.js';
import type { JobDetail, JobSnapshot } from '../../../shared/ipc-methods.js';

export function TransferDock({
  job,
  snapshot,
  more,
  cancelling,
  error,
  onView,
  onCancel,
}: {
  job: JobDetail;
  snapshot: JobSnapshot | null;
  more: number;
  cancelling: boolean;
  error: string | null;
  onView: () => void;
  onCancel: () => void;
}): JSX.Element {
  const counters = dockCounters(snapshot);
  return (
    <aside className="dock" aria-label="Active transfer">
      <span className="dock__mark" aria-hidden="true">
        <IconTransfer size={20} />
      </span>
      <div className="dock__identity">
        <span className="dock__state">{dockStateLabel(job.state)}</span>
        <span className="dock__title">
          {more > 0 ? `Transfer · +${more} more` : `Transfer · ${dockJobRef(job)}`}
        </span>
      </div>
      <div className="dock__track">
        <Progress
          percent={dockPercent(snapshot)}
          label={`Transfer progress for ${job.id}`}
          status={jobMeterStatus(job.state)}
          showValue={false}
        />
        {counters !== null ? <span className="dock__counters">{counters}</span> : null}
      </div>
      <div className="dock__actions">
        <button type="button" className="btn" onClick={onView}>
          View
        </button>
        {/* The visible word stays "Cancel" — the dock's context is on screen.
            The accessible name carries the job, at the same short reference
            the title shows, so the button is never bare "Cancel" in a
            controls list. Uses the Activity table's `jobLabel` format. */}
        <button
          type="button"
          className="btn"
          onClick={onCancel}
          disabled={cancelling}
          aria-label={jobLabel('Cancel', job.command, dockJobRef(job))}
        >
          {cancelling ? 'Cancelling…' : 'Cancel'}
        </button>
      </div>
      {error !== null ? <span className="dock__error">{error}</span> : null}
    </aside>
  );
}
