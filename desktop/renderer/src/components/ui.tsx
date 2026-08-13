/**
 * Shared UI primitives for the desktop screens.
 *
 * Safety-critical states (plan §8.2) are rendered with an explicit label
 * AND a chip color — never color alone — so the semantics survive
 * high-contrast / color-blind contexts.
 */
import type { ReactNode } from 'react';

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'attention';

const CHIP_CLASS: Record<Tone, string> = {
  neutral: 'chip',
  ok: 'chip chip--ok',
  warn: 'chip chip--warn',
  danger: 'chip chip--danger',
  attention: 'chip chip--attention',
};

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

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint ? <span className="muted">{hint}</span> : null}
    </div>
  );
}
