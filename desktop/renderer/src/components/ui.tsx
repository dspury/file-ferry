/**
 * Shared UI primitives for the desktop screens.
 *
 * Safety-critical states (plan §8.2) are rendered with an explicit label
 * AND a chip color — never color alone — so the semantics survive
 * high-contrast / color-blind contexts.
 */
import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from 'react';

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'attention';

const CHIP_CLASS = {
  neutral: 'chip',
  ok: 'chip chip--ok',
  warn: 'chip chip--warn',
  danger: 'chip chip--danger',
  attention: 'chip chip--attention',
  // `satisfies` checks every Tone is covered without widening the values
  // back to `string`, so the exact class strings stay visible to callers.
} satisfies Record<Tone, string>;

export function Chip({
  tone = 'neutral',
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}): JSX.Element {
  return <span className={CHIP_CLASS[tone]}>{children}</span>;
}

export function Panel({ title, children }: { title?: string; children: ReactNode }): JSX.Element {
  return (
    <section className="card">
      {title ? <h3 className="card__title">{title}</h3> : null}
      {children}
    </section>
  );
}

export function EmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div className="card">
      <p className="muted">{message}</p>
    </div>
  );
}

export function LoadingState({ message = 'Loading…' }: { message?: string }): JSX.Element {
  return (
    <div className="card">
      <p className="muted">{message}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }): JSX.Element {
  return (
    <div className="card">
      <p className="muted">Error: {message}</p>
    </div>
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
  hint?: string;
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
