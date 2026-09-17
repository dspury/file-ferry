/**
 * The canonical state glyph (R-7, SR-10).
 *
 * SR-10 fixes one glyph per state for the whole app, so a state survives
 * greyscale and never depends on hue alone. Before R-7 the shape lived twice:
 * `Chip` drew it with a `clip-path` and `Banner` drew a circled alert/check,
 * so the same "needs review" condition was a hollow ring in a list and an
 * alert circle in a banner. That is the defect SR-10 names, and the fix is a
 * single component both primitives render.
 *
 * The silhouettes are the SR-10 table:
 *
 *   running / active  filled triangle (pointing forward)
 *   done / ok         filled dot
 *   needs review      hollow ring
 *   failed            filled hexagon
 *   cancelled         horizontal bar
 *
 * `warn` is the sixth tone this app has and SR-10 does not name; it keeps the
 * upright warning triangle (a different orientation from the running
 * triangle, so the two still separate in greyscale). `neutral` is not a state
 * and shares the dot, muted.
 *
 * The glyph inherits `currentColor` and is always paired with the state
 * spelled out in words, so it is decorative and `aria-hidden`.
 */
import type { JSX } from 'react';
import type { Tone } from './ui.js';

/** The mark inside the 8x8 box, chosen by state. */
function mark(state: Tone): JSX.Element {
  switch (state) {
    case 'neutral':
    case 'ok':
      return <circle cx="4" cy="4" r="3.2" fill="currentColor" />;
    case 'active':
      return <polygon points="1.2,0.6 7.6,4 1.2,7.4" fill="currentColor" />;
    case 'warn':
      return <polygon points="4,0.6 7.6,7.4 0.4,7.4" fill="currentColor" />;
    case 'danger':
      return <polygon points="4,0.4 7.6,2.4 7.6,5.6 4,7.6 0.4,5.6 0.4,2.4" fill="currentColor" />;
    case 'cancelled':
      return <rect x="0.6" y="3" width="6.8" height="2" rx="0.6" fill="currentColor" />;
    case 'attention':
      // A hollow ring: the one glyph drawn as an outline, so "waiting on a
      // person" reads as unfinished business even at 8px.
      return <circle cx="4" cy="4" r="2.9" fill="none" stroke="currentColor" strokeWidth="1.6" />;
  }
}

export function StateGlyph({
  state,
  size = 8,
  className,
}: {
  state: Tone;
  size?: number | undefined;
  className?: string | undefined;
}): JSX.Element {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 8 8"
      aria-hidden="true"
      focusable="false"
    >
      {mark(state)}
    </svg>
  );
}
