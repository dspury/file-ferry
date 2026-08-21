/**
 * Destructive-action confirm dialog.
 *
 * Requires the user to type an acknowledgement phrase before the
 * destructive button is enabled (plan §4 / §10 Pkg7 step 4). This makes
 * a single click unable to destroy data and keeps the safety-critical
 * state high-contrast and explicit.
 */
import { useState } from 'react';
import { confirmEnabled, normalizePhrase } from '../lib/confirm.js';

export function ConfirmDialog({
  title,
  body,
  phrase,
  confirmLabel = 'Confirm',
  exact = true,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  phrase: string;
  confirmLabel?: string;
  exact?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}): JSX.Element {
  const [typed, setTyped] = useState('');
  const enabled = exact
    ? normalizePhrase(typed) === normalizePhrase(phrase)
    : confirmEnabled({ phrase, typed, exact });

  return (
    <div className="confirm" role="alertdialog" aria-modal="true" aria-label={title}>
      <h3>{title}</h3>
      <p>{body}</p>
      {exact ? (
        <div className="field">
          <label>
            Type <strong>{phrase}</strong> to confirm
          </label>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
        </div>
      ) : null}
      <div className="row">
        <button className="btn btn--danger" onClick={onConfirm} disabled={!enabled}>
          {confirmLabel}
        </button>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
