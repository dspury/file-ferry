/**
 * Destructive-action confirm dialog.
 *
 * Requires the user to type an acknowledgement phrase before the
 * destructive button is enabled (plan §4 / §10 Pkg7 step 4). This makes
 * a single click unable to destroy data and keeps the safety-critical
 * state high-contrast and explicit.
 *
 * As a modal it also traps Tab focus and closes on Escape (WCAG 2.4.3):
 * `aria-modal` is a promise to assistive tech that the rest of the UI is
 * inert, so focus must not be able to wander out behind the dialog. The
 * backdrop is what makes that promise true for sighted users too — the
 * dialog used to render inline at the bottom of the page, below the
 * content it was blocking.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { confirmEnabled, normalizePhrase } from '../lib/confirm.js';
import { FOCUSABLE_SELECTOR, isTrapKey, nextFocusIndex } from '../lib/focus-trap.js';
import { IconAlert } from './icons.js';

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
  const bodyId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const enabled = exact
    ? normalizePhrase(typed) === normalizePhrase(phrase)
    : confirmEnabled({ phrase, typed, exact });

  // Pull focus into the dialog on open and hand it back to whatever had it
  // when the dialog closes, so a keyboard user is not dumped at the top of
  // the document. When `exact` is false there is no input to autoFocus, so
  // the first focusable element (the confirm button) takes it.
  useEffect(() => {
    // SAFETY: `document.activeElement` is typed `Element | null`, but focus
    // restoration only makes sense for an HTMLElement. The narrowing is not
    // trusted — the call below is optional (`restoreTo?.focus?.()`), so a
    // non-HTML element (an SVG node) simply does not get focused back.
    const restoreTo = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (root && !root.contains(document.activeElement)) {
      root.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus();
    }
    return () => restoreTo?.focus?.();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onCancel();
      return;
    }
    if (!isTrapKey(e.key)) return;
    const root = dialogRef.current;
    if (!root) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    // SAFETY: used only as the needle for `indexOf` against a list of
    // HTMLElements. A null or non-HTML activeElement simply is not found,
    // yielding -1, which `nextFocusIndex` already handles as "focus is
    // outside the trap".
    const target = nextFocusIndex(
      items.indexOf(document.activeElement as HTMLElement),
      items.length,
      e.shiftKey,
    );
    if (target === null) return;
    e.preventDefault();
    items[target]?.focus();
  };

  return (
    <div className="modal">
      <div
        className="confirm"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        // The body is the whole warning -- that the source files are deleted
        // and that ferry cannot undo it. Without this it was a loose
        // paragraph: `aria-modal` prunes everything outside the dialog from
        // the platform tree, focus goes straight to the phrase field, and
        // the announcement was the dialog's name and then the field's,
        // with the sentence in between never read. `aria-describedby` makes
        // it part of what opening the dialog says.
        aria-describedby={bodyId}
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="confirm__title">
          <IconAlert size={18} />
          {title}
        </h2>
        <p id={bodyId}>{body}</p>
        {exact ? (
          <div className="field">
            <label htmlFor="confirm-phrase">
              Type <strong>{phrase}</strong> to confirm
            </label>
            <input
              id="confirm-phrase"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoFocus
            />
          </div>
        ) : null}
        <div className="row">
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn btn--danger" onClick={onConfirm} disabled={!enabled}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
