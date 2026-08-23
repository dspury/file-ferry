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

/**
 * A parsed location hash: which view, plus that view's own parameters.
 *
 * The hash is the whole navigation state, so anything a screen needs to
 * restore itself belongs in it — a selected asset survives a reload, and a
 * link from Projects can hand Media a filter. The form is
 * `#/<view>?<key>=<value>`: a query string rather than positional segments,
 * so a parameter is named at the call site and two of them cannot be
 * transposed.
 */
export interface Route {
  readonly viewId: string;
  readonly params: ReadonlyMap<string, string>;
}

const HASH_PATTERN = /^#\/([a-z-]+)(?:\?(.*))?$/;

/** Parse a location hash. Anything unrecognised falls back to `defaultId`. */
export function parseRoute(hash: string, defaultId: string): Route {
  const match = HASH_PATTERN.exec(hash);
  if (match === null) {
    return { viewId: defaultId, params: new Map() };
  }
  const params = new Map<string, string>();
  for (const [key, value] of new URLSearchParams(match[2] ?? '')) {
    // A repeated key keeps its first value: a hand-edited or truncated hash
    // should resolve to something, not to the last thing that was appended.
    if (!params.has(key)) params.set(key, value);
  }
  return { viewId: match[1] ?? defaultId, params };
}

/** Build the hash for a view and its parameters. */
export function routeHash(viewId: string, params: Readonly<Record<string, string>> = {}): string {
  const query = new URLSearchParams(params).toString();
  return query === '' ? `#/${viewId}` : `#/${viewId}?${query}`;
}

/** Set the active view, and optionally its parameters, in the hash. */
export function navigateTo(viewId: string, params?: Readonly<Record<string, string>>): void {
  window.location.hash = routeHash(viewId, params ?? {}).slice(1);
}
