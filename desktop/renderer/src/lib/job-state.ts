/**
 * Pure job-state presentation logic (testable without React/DOM).
 *
 * Before this, Home and Activity each carried their own state -> chip
 * mapping and the two disagreed about the same job: Home drew `running`
 * green (the tone it uses for success) while Activity drew it grey, and
 * both fell through to an untoned chip for `succeeded` and `cancelled`, so
 * a good outcome and an aborted one rendered as the same plate. One mapping
 * used by both screens is the only way those can't drift again.
 *
 * Nothing here decides what a job *does*; it decides how a state that the
 * sidecar already reported is drawn.
 */

/** Chip / tile tones, matching the `Tone` union the primitives accept. */
export type StateTone = 'neutral' | 'active' | 'ok' | 'warn' | 'danger' | 'cancelled' | 'attention';

/**
 * How a progress meter should be *read*, which is not the same question as
 * what number it is showing.
 *
 * `running` is the only status whose fill means "and still climbing".
 * `complete` is the only one that may draw a full bar, because it is the
 * only one where the underlying operation has been confirmed. The three
 * halted statuses draw their fill at the point work stopped and rule the
 * remainder out, so the number reads as "got this far" and never as
 * "this fraction done".
 */
export type MeterStatus = 'idle' | 'running' | 'stalled' | 'complete' | 'failed' | 'cancelled';

/**
 * The chip tone for a job state.
 *
 * The lifecycle these ten states come from, per `application/jobs.py`:
 *
 *   planned -> awaiting_review -> queued -> running -> verifying -> succeeded
 *                     |             |         |           |
 *                 cancelled     cancelled  needs_attention failed
 *                                             |
 *                                          resumable
 *
 * `state` is typed `string` on the wire, so the default is load-bearing
 * rather than unreachable: a sidecar that grows a state must draw a quiet
 * chip, not blank the Activity table.
 */
export function jobStateTone(state: string): StateTone {
  switch (state) {
    // In flight. The accent, not green: a job that is still copying has not
    // succeeded, and reusing the success tone for it is what made Home read
    // "RUNNING" as a completed row.
    case 'queued':
    case 'running':
    case 'verifying':
    case 'resumable':
      return 'active';

    // A human has to decide something.
    case 'needs_attention':
    case 'awaiting_review':
      return 'attention';

    // Terminal, and three different outcomes.
    case 'succeeded':
      return 'ok';
    case 'failed':
      return 'danger';
    case 'cancelled':
      return 'cancelled';

    // `planned` is created but not yet submitted for review: nothing is
    // happening and nothing is wrong. Deliberately not `attention` -- the
    // Activity filter of that name is keyed on ATTENTION_STATES, which does
    // not include `planned`, and a chip promising a filter that would hide
    // the row is worse than a quiet one.
    default:
      return 'neutral';
  }
}

/** How the job's progress meter should be read. */
export function jobMeterStatus(state: string): MeterStatus {
  switch (state) {
    case 'queued':
    case 'running':
    case 'verifying':
    case 'resumable':
      return 'running';

    // Non-terminal but not moving: the bar must not read as climbing while
    // the job sits waiting for an operator.
    case 'needs_attention':
      return 'stalled';

    case 'succeeded':
      return 'complete';
    case 'failed':
      return 'failed';
    case 'cancelled':
      return 'cancelled';

    // `planned` and `awaiting_review` have done no work to report.
    default:
      return 'idle';
  }
}

/**
 * True when the job stopped without finishing its work.
 *
 * The receipt for one of these is the document that decides whether a
 * camera card can be released, so the screens use this to promote the
 * job's own error text into a banner instead of leaving it in the data.
 */
export function jobIncomplete(state: string): boolean {
  const status = jobMeterStatus(state);
  return status === 'failed' || status === 'cancelled' || status === 'stalled';
}

/**
 * Banner severity for a job's error text.
 *
 * `failed` is over — the run is not coming back on its own. `cancelled` and
 * `needs_attention` still have a path forward (retry, resume), so they are
 * warnings, which is also what keeps a resumable job from being dressed in
 * the same red as an abandoned one.
 */
export function jobErrorTone(state: string): 'danger' | 'warn' {
  return state === 'failed' ? 'danger' : 'warn';
}

/**
 * The stamped word on the banner carrying a job's error text.
 *
 * It has to name what happened rather than restate the severity, and it has
 * to be the *right* word: an operator reading "HELD" over a cancelled run
 * would go looking for the thing holding it.
 */
export function jobNoteLabel(state: string): string {
  switch (state) {
    case 'failed':
      return 'Failed';
    case 'cancelled':
      return 'Cancelled';
    default:
      return 'Held';
  }
}
