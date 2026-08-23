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

/**
 * The six operational states an offload, proxy run, or replica can be in,
 * plus `attention` for "a human has to look at this". `active` and
 * `cancelled` exist so a running job and a job an operator stopped are not
 * both forced through `neutral`; their token treatments live in styles.css.
 */
export type Tone = 'neutral' | 'active' | 'ok' | 'warn' | 'danger' | 'cancelled' | 'attention';

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
}: {
  message: string;
  hint?: string | undefined;
  action?: ReactNode | undefined;
}): JSX.Element {
  return (
    <div className="empty">
      {/* The glyph is framed rather than floating: an empty panel is a
          place something goes, and the plate plus the dashed well around
          it say so before the sentence is read. */}
      <span className="empty__frame" aria-hidden="true">
        <IconInbox />
      </span>
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
 * already has. #88 owns what a wait says per screen; this is the container.
 */
export function LoadingState({ message = 'Loading…' }: { message?: string }): JSX.Element {
  return (
    <div className="empty empty--busy" aria-busy="true" aria-live="polite">
      <p className="muted">{message}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }): JSX.Element {
  return <Banner tone="danger">{message}</Banner>;
}

const BANNER_ICON = {
  ok: IconCheck,
  warn: IconAlert,
  danger: IconAlert,
  info: IconInfo,
} satisfies Record<BannerTone, (props: { size?: number }) => JSX.Element>;

const BANNER_LABEL = {
  ok: 'Done',
  warn: 'Warning',
  danger: 'Error',
  info: 'Note',
} satisfies Record<BannerTone, string>;

export type BannerTone = 'ok' | 'warn' | 'danger' | 'info';

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
}

/**
 * Progress through a plan -> review -> execute -> verify sequence.
 *
 * Ingest and Organize both gate later stages on earlier ones, and before
 * this the only cue was a row of disabled buttons. An ordered list is the
 * honest markup: `aria-current="step"` names where you are, and the
 * completed ones say so in text rather than only by colour.
 */
export function Steps({
  label,
  steps,
  activeId,
}: {
  label: string;
  steps: readonly StepDef[];
  activeId: string;
}): JSX.Element {
  const activeIndex = steps.findIndex((s) => s.id === activeId);
  return (
    <ol className="steps" aria-label={label}>
      {steps.map((step, index) => {
        const done = activeIndex > index;
        const active = activeIndex === index;
        const state = done ? ' step--done' : active ? ' step--active' : '';
        return (
          <li key={step.id} className={`step${state}`} aria-current={active ? 'step' : undefined}>
            <span className="step__index" aria-hidden="true">
              {done ? '✓' : index + 1}
            </span>
            {step.label}
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
 * path is shown right-to-left so the tail — the part that identifies the
 * folder — survives truncation instead of the volume root.
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
        {value ?? placeholder}
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
 * Determinate progress meter.
 *
 * Carries explicit `progressbar` semantics (WCAG 4.1.2) — without them a
 * screen reader sees two nested divs and announces nothing. `aria-valuetext`
 * gives the percentage a spoken form, and the label names which job the
 * meter belongs to so a table of them stays distinguishable.
 */
export function Progress({
  percent,
  label,
  tone = 'neutral',
  showValue = true,
}: {
  percent: number;
  label: string;
  tone?: 'neutral' | 'ok' | 'danger' | undefined;
  showValue?: boolean | undefined;
}): JSX.Element {
  const cls = tone === 'neutral' ? 'progress' : `progress progress--${tone}`;
  return (
    <div className="progress-cell">
      <div
        className={cls}
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={`${percent}%`}
        aria-label={label}
      >
        <div className="progress__fill" style={{ width: `${percent}%` }} />
      </div>
      {showValue ? (
        <span className="progress-cell__pct" aria-hidden="true">
          {percent}%
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
 * A path shown in running text or a table cell. Truncates from the left so
 * the filename stays visible, and keeps the full value in a tooltip.
 */
export function PathCell({ path }: { path: string }): JSX.Element {
  return (
    <span className="cell-path" title={path}>
      {path}
    </span>
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
