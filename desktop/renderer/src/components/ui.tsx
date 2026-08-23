/**
 * Shared UI primitives for the desktop screens.
 *
 * The screens are meant to be thin: they choose which primitive says what,
 * and everything about how it looks lives here and in styles.css. A screen
 * that reaches for an inline `style` or a bare `<div className="card">` is
 * a sign a primitive is missing.
 *
 * Safety-critical states (plan §8.2) are rendered with an explicit label
 * AND a chip colour — never colour alone — so the semantics survive
 * high-contrast / colour-blind contexts.
 */
import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from 'react';
import { IconAlert, IconCheck, IconInbox, IconInfo } from './icons.js';
import { splitPathTail } from '../lib/format.js';
import type { MeterStatus, StateTone } from '../lib/job-state.js';

/**
 * The six operational states an offload, proxy run, or replica can be in,
 * plus `attention` for "a human has to look at this". `active` and
 * `cancelled` exist so a running job and a job an operator stopped are not
 * both forced through `neutral`; their token treatments live in styles.css.
 *
 * Defined in `lib/job-state.ts` so the pure mappers that produce a tone can
 * be unit-tested without importing a module that renders JSX.
 */
export type Tone = StateTone;

const CHIP_CLASS = {
  neutral: 'chip',
  active: 'chip chip--active',
  ok: 'chip chip--ok',
  warn: 'chip chip--warn',
  danger: 'chip chip--danger',
  cancelled: 'chip chip--cancelled',
  attention: 'chip chip--attention',
  // `satisfies` checks every Tone is covered without widening the values
  // back to `string`, so the exact class strings stay visible to callers.
} satisfies Record<Tone, string>;

/**
 * A state pill. The dot is decorative — the state is always spelled out in
 * the chip's own text, which is what a screen reader and a greyscale
 * display both fall back to.
 */
export function Chip({
  tone = 'neutral',
  children,
}: {
  tone?: Tone | undefined;
  children: ReactNode;
}): JSX.Element {
  return (
    <span className={CHIP_CLASS[tone]}>
      <span className="chip__dot" aria-hidden="true" />
      {children}
    </span>
  );
}

/** The three things a passive readout can be reporting. */
export type StatusTone = 'ok' | 'danger' | 'neutral';

/**
 * A passive hardware readout: a small tone dot and faint mono text on a
 * recessed plate.
 *
 * This is deliberately *not* a `Chip`. A chip is a state pill sized and
 * coloured for a state a row is in, and the accent tier of it (`active`) is
 * reserved for live work and pressable things. A readout reports a
 * condition of the app itself — the sidecar is up, the event subscription
 * is open — which is neither. It says the same thing more quietly, and the
 * dot is the only coloured pixel in it.
 *
 * `live` opts into `role="status"`. It is off by default: a readout whose
 * text changes as a count ticks would announce itself on every change,
 * which is chatter rather than news. Only the connection indicator — where
 * the transition genuinely has to interrupt — asks for it.
 */
export function StatusReadout({
  tone = 'neutral',
  live = false,
  children,
}: {
  tone?: StatusTone | undefined;
  live?: boolean | undefined;
  children: ReactNode;
}): JSX.Element {
  return (
    <span className={`status status--${tone}`} role={live ? 'status' : undefined}>
      <span className="status__dot" aria-hidden="true" />
      {children}
    </span>
  );
}

/**
 * A titled section.
 *
 * `actions` sit on the title row so a section's controls are adjacent to
 * what they act on rather than stranded at the bottom of the screen.
 * `flush` drops the body padding for a table that should reach the card's
 * edges.
 */
export function Panel({
  title,
  description,
  actions,
  flush = false,
  children,
}: {
  title?: string | undefined;
  description?: string | undefined;
  actions?: ReactNode | undefined;
  flush?: boolean | undefined;
  children: ReactNode;
}): JSX.Element {
  const hasHeader = title !== undefined || actions !== undefined;
  return (
    <section className="card">
      {hasHeader ? (
        <div className="card__header">
          <div>
            {title === undefined ? null : <h3 className="card__title">{title}</h3>}
            {description === undefined ? null : <p className="card__desc">{description}</p>}
          </div>
          {actions === undefined ? null : <div className="card__actions">{actions}</div>}
        </div>
      ) : null}
      <div className={flush ? 'card__body card__body--flush' : 'card__body'}>{children}</div>
    </section>
  );
}

/**
 * How much ceremony an empty well is allowed.
 *
 * `full` is the default: framed glyph, a 15px title, a hint with room to
 * wrap. `compact` drops the glyph and steps the type and padding down.
 *
 * It exists because a screen can be *nothing but* empty states — a
 * first-run Dashboard is two of them, Media's asset detail is three — and
 * at that point the ceremony is what pushes the one actionable thing off
 * the fold. The rule is one full well per screen: whichever panel owns the
 * action an operator would take next earns the frame, and every other well
 * on that screen states its condition compactly. That keeps the emphasis
 * where the next move is instead of spending it evenly on panels that have
 * nothing to offer.
 */
export type EmptyDensity = 'full' | 'compact';

/**
 * Nothing-here state.
 *
 * An empty list is a moment where the operator most needs telling what to
 * do next, so `hint` and `action` are first-class rather than a muted
 * sentence buried in a card.
 */
export function EmptyState({
  message,
  hint,
  action,
  density = 'full',
}: {
  message: string;
  hint?: string | undefined;
  action?: ReactNode | undefined;
  density?: EmptyDensity | undefined;
}): JSX.Element {
  return (
    <div className={density === 'compact' ? 'empty empty--compact' : 'empty'}>
      {/* The glyph is framed rather than floating: an empty panel is a
          place something goes, and the plate plus the dashed well around
          it say so before the sentence is read. Dropped entirely in the
          compact density rather than shrunk — a 28px plate reads as a
          smaller version of the same ornament, and the point of compact is
          that this well is not the one asking to be looked at. */}
      {density === 'compact' ? null : (
        <span className="empty__frame" aria-hidden="true">
          <IconInbox />
        </span>
      )}
      <p className="empty__title">{message}</p>
      {hint === undefined ? null : <p className="empty__hint">{hint}</p>}
      {action === undefined ? null : <div className="empty__actions">{action}</div>}
    </div>
  );
}

/**
 * Busy state. `aria-busy` plus a polite live region means the wait is
 * announced instead of the screen just going quiet.
 *
 * It shares `EmptyState`'s centring but not its dashed well: "put something
 * here" is the wrong instruction while the app is fetching something it
 * already has.
 *
 * The sliding bar is the only thing on screen that says the app is still
 * working rather than finished and empty, and it is deliberately
 * *indeterminate* — nothing here knows how far along the request is, and a
 * bar parked at some fraction would be a claim. Under
 * `prefers-reduced-motion` it is removed rather than frozen, because a
 * stationary partial bar is exactly the false claim it exists to avoid.
 */
export function LoadingState({
  message = 'Loading…',
  hint,
}: {
  message?: string;
  hint?: string | undefined;
}): JSX.Element {
  return (
    <div className="empty empty--busy" aria-busy="true" aria-live="polite">
      <span className="busy__meter" aria-hidden="true">
        <span className="busy__sweep" />
      </span>
      <p className="empty__title">{message}</p>
      {hint === undefined ? null : <p className="empty__hint">{hint}</p>}
    </div>
  );
}

/**
 * A whole screen that has nothing to show yet.
 *
 * Six of the eight screens returned a bare `LoadingState` from their page
 * root, which put a single grey sentence at the top of an otherwise blank
 * content area — indistinguishable from a screen that had loaded and found
 * nothing. Framing the wait in the same card the content will arrive in
 * keeps the page's shape stable across the transition.
 */
export function ScreenLoading({
  message,
  hint,
}: {
  message: string;
  hint?: string | undefined;
}): JSX.Element {
  return (
    <div className="page">
      <Panel>
        <LoadingState message={message} hint={hint} />
      </Panel>
    </div>
  );
}

/**
 * A screen that could not load at all.
 *
 * The bare banner this replaces stated the failure and stopped there,
 * leaving an operator with a red sentence in an empty room and no way
 * forward. A load failure is nearly always transient (the sidecar is
 * restarting), so the retry is the point.
 */
export function ScreenError({
  message,
  hint = 'The sidecar may still be starting. Retrying costs nothing — no media is touched by a failed read.',
  onRetry,
}: {
  message: string;
  hint?: string | undefined;
  onRetry?: (() => void) | undefined;
}): JSX.Element {
  return (
    <div className="page">
      <Panel>
        <div className="stack">
          <Banner tone="danger" label="Cannot load">
            {message}
          </Banner>
          <p className="muted">{hint}</p>
          {onRetry === undefined ? null : (
            <div className="row">
              <button type="button" className="btn btn--primary" onClick={onRetry}>
                Retry
              </button>
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}

const BANNER_ICON = {
  ok: IconCheck,
  warn: IconAlert,
  danger: IconAlert,
  attention: IconAlert,
  info: IconInfo,
} satisfies Record<BannerTone, (props: { size?: number }) => JSX.Element>;

const BANNER_LABEL = {
  ok: 'Done',
  warn: 'Warning',
  danger: 'Error',
  attention: 'Needs review',
  info: 'Note',
} satisfies Record<BannerTone, string>;

/*
 * `attention` is the same tier the chips call attention: a condition a person
 * has to decide about rather than a failure or a warning about a failure. It
 * is here so a screen that has already derived that severity can say it in
 * one hue instead of two.
 */
export type BannerTone = 'ok' | 'warn' | 'danger' | 'attention' | 'info';

/**
 * An inline message with room to be read.
 *
 * Errors used to be rendered as `Chip`s, which squeezed a sentence into a
 * pill sized for one word. A banner also states its severity in words
 * ("Error: …"), so the meaning does not rest on the colour, and asserts
 * `role="alert"` when it is one so it is announced on arrival.
 */
export function Banner({
  tone = 'info',
  label,
  children,
}: {
  tone?: BannerTone | undefined;
  label?: string | undefined;
  children: ReactNode;
}): JSX.Element {
  const Glyph = BANNER_ICON[tone];
  const prefix = label ?? BANNER_LABEL[tone];
  return (
    <div className={`banner banner--${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
      <Glyph size={16} />
      <div className="banner__body">
        <span className="banner__label">{prefix}: </span>
        {children}
      </div>
    </div>
  );
}

/** A headline figure. The label always names the state the count is of. */
export function StatCard({
  label,
  value,
  tone = 'neutral',
  meta,
}: {
  label: string;
  value: number | string;
  tone?: Tone | undefined;
  meta?: string | undefined;
}): JSX.Element {
  const cls = tone === 'neutral' ? 'stat' : `stat stat--${tone}`;
  return (
    <div className={cls}>
      <span className="stat__label">{label}</span>
      <span className="stat__value">{value}</span>
      {meta === undefined ? null : <span className="stat__meta">{meta}</span>}
    </div>
  );
}

/**
 * Mutually-exclusive filter switch.
 *
 * Rendered as a radio group, not a row of buttons: the options are one
 * choice with one answer, and `aria-checked` tells assistive tech which is
 * selected. As buttons they announced identically whether active or not.
 */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (next: T) => void;
}): JSX.Element {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={option === value}
          className={`seg__item${option === value ? ' seg__item--active' : ''}`}
          onClick={() => onChange(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

export interface StepDef {
  readonly id: string;
  readonly label: string;
  /**
   * This stage, and every stage after it, can write to disk.
   *
   * The first such stage is where the flow stops being reversible, and it
   * is the one distinction in the rail that carries real consequence — up
   * to it, Offload and Organize have only read and planned. Marking it is
   * what lets an operator see at a glance which side of the line they are
   * standing on.
   */
  readonly writes?: boolean;
}

/**
 * The severity the *current* stage is reporting.
 *
 * `accent` is the resting case: the stage is simply where the flow has got
 * to. The other two exist for a terminal stage that has an outcome, because
 * "you have arrived at the last stage" and "the last stage went well" are
 * two different claims and the rail was making the second one for free. A
 * toned stage always changes its *label* too (`DONE` -> `INCOMPLETE`), so
 * the severity never rests on the plate colour alone.
 */
export type StepTone = 'accent' | 'warn' | 'danger';

/**
 * Progress through a plan -> review -> execute -> verify sequence.
 *
 * Ingest and Organize both gate later stages on earlier ones, and before
 * this the only cue was a row of disabled buttons. An ordered list is the
 * honest markup: `aria-current="step"` names where you are, and the
 * completed ones say so in text rather than only by colour.
 *
 * Three channels separate the three stage conditions, so none of them rests
 * on hue: a pending stage shows its number on a quiet plate, a finished one
 * shows a check and a visually-hidden "(completed)", and the active one is
 * the only `aria-current="step"` — and the only stage drawn as an enclosed,
 * lit plate with its label at full contrast.
 */
export function Steps({
  label,
  steps,
  activeId,
  activeTone = 'accent',
}: {
  label: string;
  steps: readonly StepDef[];
  activeId: string;
  activeTone?: StepTone | undefined;
}): JSX.Element {
  const activeIndex = steps.findIndex((s) => s.id === activeId);
  const gateIndex = steps.findIndex((s) => s.writes === true);
  return (
    <ol className="steps" aria-label={label}>
      {steps.map((step, index) => {
        const done = activeIndex > index;
        const active = activeIndex === index;
        const tone = active && activeTone !== 'accent' ? ` step--active-${activeTone}` : '';
        const state = done ? ' step--done' : active ? ` step--active${tone}` : '';
        // Only the first writing stage carries the marker: it is a boundary,
        // not a property each later stage repeats.
        const gate = index === gateIndex && gateIndex > 0;
        return (
          <li
            key={step.id}
            className={`step${state}${gate ? ' step--gate' : ''}`}
            aria-current={active ? 'step' : undefined}
          >
            {gate ? (
              <span className="step__gate" aria-hidden="true">
                writes
              </span>
            ) : null}
            <span className="step__index" aria-hidden="true">
              {done ? '✓' : index + 1}
            </span>
            {step.label}
            {gate ? (
              <span className="visually-hidden"> (from here on, ferry writes to disk)</span>
            ) : null}
            {done ? <span className="visually-hidden"> (completed)</span> : null}
            {index < steps.length - 1 ? <span className="step__sep" aria-hidden="true" /> : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Folder chooser.
 *
 * The chosen path and the button that changes it read as one control. The
 * directory run is what gives way under truncation, so the folder name — the
 * part that identifies the choice — always survives.
 */
export function PathPicker({
  value,
  placeholder = 'No folder chosen',
  buttonLabel = 'Choose…',
  onPick,
  disabled = false,
  id,
  'aria-describedby': describedBy,
}: {
  value: string | null;
  placeholder?: string | undefined;
  buttonLabel?: string | undefined;
  onPick: () => void;
  disabled?: boolean | undefined;
  id?: string | undefined;
  'aria-describedby'?: string | undefined;
}): JSX.Element {
  const valueId = useId();
  return (
    <div className="pathpick">
      <span
        className={value === null ? 'pathpick__value pathpick__value--empty' : 'pathpick__value'}
        id={valueId}
        title={value ?? undefined}
      >
        {value === null ? placeholder : <PathText path={value} />}
      </span>
      <button
        type="button"
        className="btn"
        onClick={onPick}
        disabled={disabled}
        id={id}
        // The button alone would announce as a bare "Choose…"; naming it
        // with the field's label and the current value makes it clear
        // which folder is being changed and what it is set to now.
        aria-describedby={describedBy === undefined ? valueId : `${describedBy} ${valueId}`}
      >
        {buttonLabel}
      </button>
    </div>
  );
}

/**
 * The word stamped under the number, which is what stops a fraction being
 * read as a claim about completion. `null` where the number speaks for
 * itself: a moving job's "62%" needs no qualifier, and an idle one shows a
 * dash instead of a figure.
 */
const METER_NOTE = {
  idle: null,
  running: null,
  stalled: 'held',
  complete: 'done',
  failed: 'stopped',
  cancelled: 'stopped',
} satisfies Record<MeterStatus, string | null>;

/** What a screen reader is told, which must say the same thing as the plate. */
function meterValueText(status: MeterStatus, percent: number): string {
  switch (status) {
    case 'idle':
      return 'not started';
    case 'running':
      return `${percent}%`;
    case 'stalled':
      return `held at ${percent}% — waiting for you`;
    case 'complete':
      return 'complete';
    case 'failed':
      return `stopped at ${percent}% — did not complete`;
    case 'cancelled':
      return `cancelled at ${percent}% — did not complete`;
  }
}

/**
 * Progress meter.
 *
 * Carries explicit `progressbar` semantics (WCAG 4.1.2) — without them a
 * screen reader sees two nested divs and announces nothing. The label names
 * which job the meter belongs to so a table of them stays distinguishable.
 *
 * `status` is separate from `percent` because the number alone cannot say
 * whether it is still climbing, and the whole point of this meter is that it
 * must never imply completion before the operation is confirmed:
 *
 *  - `complete` is the only status allowed to draw a full bar, and it draws
 *    one regardless of `percent`. A finished job holds no live snapshot, so
 *    the counters report 0 for it — which is how a succeeded offload used to
 *    render as an empty track next to the text "0%".
 *  - `failed`, `cancelled` and `stalled` fill to where work stopped and rule
 *    the remainder out with a hatch, and the plate reads "25% / STOPPED"
 *    rather than a bare "25%". The number is where it got to, not how much
 *    of it is done.
 *  - `running` is the only fill that means "and climbing". At 100% it is
 *    still visibly not the completion treatment: a different hue, and the
 *    word beside it is a percentage rather than DONE.
 */
export function Progress({
  percent,
  label,
  status = 'running',
  showValue = true,
}: {
  percent: number;
  label: string;
  status?: MeterStatus | undefined;
  showValue?: boolean | undefined;
}): JSX.Element {
  const filled = status === 'complete' ? 100 : percent;
  const note = METER_NOTE[status];
  return (
    <div className="progress-cell">
      <div
        className={`progress progress--${status}`}
        role="progressbar"
        aria-valuenow={filled}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={meterValueText(status, percent)}
        aria-label={label}
      >
        <div className="progress__fill" style={{ width: `${filled}%` }} />
      </div>
      {showValue ? (
        // aria-hidden: `aria-valuetext` above already says all of this, and
        // says it more precisely than the two stacked words can.
        <span className="progress-cell__value" aria-hidden="true">
          <span className="progress-cell__pct">{status === 'idle' ? '—' : `${filled}%`}</span>
          {note === null ? null : <span className="progress-cell__note">{note}</span>}
        </span>
      ) : null}
    </div>
  );
}

export interface KeyValueRow {
  readonly label: string;
  readonly value: ReactNode;
}

/** A definition list for read-only metadata. */
export function KeyValue({ rows }: { rows: readonly KeyValueRow[] }): JSX.Element {
  return (
    <dl className="kv">
      {rows.map((row) => (
        // `display: contents` lets each pair be one element for React's key
        // while the dt/dd still land in the parent grid's columns.
        <div className="kv__pair" key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * A path shown in running text or a table cell. Truncates the directory run
 * so the filename stays visible, and keeps the full value in a tooltip.
 */
export function PathCell({ path }: { path: string }): JSX.Element {
  return (
    <span className="cell-path" title={path}>
      <PathText path={path} />
    </span>
  );
}

/**
 * The two halves of a truncated path.
 *
 * See `splitPathTail`: the previous treatment leaned on `direction: rtl` to
 * keep the tail, and the bidi algorithm moved the leading `/` of an absolute
 * path to the wrong end in the process. Here the head is the only part
 * allowed to shrink (`flex-shrink` 1 against the tail's 0), so the leaf
 * survives and every character stays where the path put it.
 */
function PathText({ path }: { path: string }): JSX.Element {
  const { head, tail } = splitPathTail(path);
  return (
    <>
      {head === '' ? null : <span className="path__head">{head}</span>}
      <span className="path__tail">{tail}</span>
    </>
  );
}

/**
 * Labelled form control.
 *
 * The label is bound to the control programmatically (WCAG 1.3.1 / 4.1.2):
 * `Field` mints an id and clones it onto its child, so screen readers
 * announce the label with the input instead of seeing an unnamed field. A
 * `hint` is wired the same way via `aria-describedby`. A child that already
 * carries an `id` keeps it, and a non-element child (or several) falls back
 * to wrapping — the label still names the control through containment.
 */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string | undefined;
  children: ReactNode;
}): JSX.Element {
  const reactId = useId();
  const hintId = hint ? `${reactId}-hint` : null;
  // SAFETY: guarded by `isValidElement` on the same line, so `children` is a
  // React element here. Its props are then only *read* optionally (`id`,
  // `aria-describedby`), and both are re-supplied via cloneElement, so an
  // element without them is handled rather than assumed.
  const single = isValidElement(children) ? (children as ReactElement<ControlProps>) : null;

  let control: ReactNode = children;
  let controlId: string | null = null;
  if (single) {
    controlId = single.props.id ?? reactId;
    const describedBy = joinIds(single.props['aria-describedby'] ?? null, hintId);
    // `aria-describedby` is only set when there is a hint (or the caller
    // already supplied one); under exactOptionalPropertyTypes it cannot be
    // passed as an explicit undefined.
    const idProp: ControlProps = { id: controlId };
    control = cloneElement(
      single,
      describedBy === null ? idProp : { ...idProp, 'aria-describedby': describedBy },
    );
  }

  return (
    <div className="field">
      {controlId === null ? <label>{label}</label> : <label htmlFor={controlId}>{label}</label>}
      {control}
      {hintId === null ? null : (
        <span className="muted" id={hintId}>
          {hint}
        </span>
      )}
    </div>
  );
}

type ControlProps = { id?: string; 'aria-describedby'?: string };

/** Append the hint id to any describedby the caller already set. */
function joinIds(existing: string | null, hintId: string | null): string | null {
  const ids = [existing, hintId].filter((v): v is string => v !== null && v !== '');
  return ids.length > 0 ? ids.join(' ') : null;
}
