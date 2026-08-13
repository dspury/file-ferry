/**
 * View registry for the desktop shell.
 *
 * A dependency-free hash-based view switcher (plan §7a: no new dep
 * surface). Each view has an id, label, and the screen component. The
 * active view is derived from the URL hash (e.g. `#/ingest`).
 */

import type { ComponentType } from 'react';

export interface ViewDef {
  readonly id: string;
  readonly label: string;
  readonly component: ComponentType;
}

/** Read the active view id from the current location hash. */
export function activeViewId(defaultId: string): string {
  const hash = window.location.hash;
  const match = hash.match(/^#\/([a-z-]+)/);
  return match ? (match[1] ?? defaultId) : defaultId;
}

/** Set the active view in the hash. */
export function navigateTo(viewId: string): void {
  window.location.hash = `/${viewId}`;
}
