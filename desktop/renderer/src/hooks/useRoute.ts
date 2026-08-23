/**
 * The current hash route, re-read whenever it changes.
 *
 * A screen that keeps state in the hash (which asset is selected, which
 * project the list is filtered to) cannot rely on the shell re-rendering
 * it: the shell only tracks the *view* id, and navigating from
 * `#/asset` to `#/asset?id=…` leaves that id identical, so React bails out
 * of the update. Subscribing here means a screen sees its own parameters
 * change.
 */
import { useEffect, useState } from 'react';
import { parseRoute, type Route } from '../views.js';

export function useRoute(defaultId: string): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash, defaultId));

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute(window.location.hash, defaultId));
    // The hash may already have moved between the initial render and this
    // effect running, so re-read once rather than waiting for the next event.
    onHashChange();
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [defaultId]);

  return route;
}
