/**
 * Temporary screen body for views that land in a later Package 7
 * sub-package. Each screen is replaced by its real implementation in
 * 7b/7c/7d; the shell, nav, and design system are wired here first.
 */

interface Props {
  readonly title: string;
  readonly note: string;
}

export function Placeholder({ title, note }: Props): JSX.Element {
  return (
    <div className="stack">
      <h2>{title}</h2>
      <div className="card">
        <p className="muted">{note}</p>
      </div>
    </div>
  );
}
