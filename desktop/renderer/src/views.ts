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
  /** Shown beside the title in the header, so a screen never has to
   *  re-state what it is in its own body. */
  readonly description: string;
  readonly icon: ComponentType<{ size?: number }>;
  readonly component: ComponentType;
}

/**
 * A labelled run of nav items.
 *
 * The rail used to be eight equal-weight entries in the order they were
 * built, which gave no clue that Offload and Organize are the two jobs the
 * app exists to do, or that Environment and Settings are somewhere you go
 * once. Grouping states that; `footer` pins the maintenance group to the
 * bottom of the rail, away from the daily work.
 */
export interface NavGroup {
  readonly id: string;
  readonly label: string;
  readonly footer?: boolean;
  readonly views: readonly ViewDef[];
}

/** Flatten the groups into visual order — what arrow-key nav traverses. */
export function flattenViews(groups: readonly NavGroup[]): readonly ViewDef[] {
  return groups.flatMap((g) => g.views);
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
