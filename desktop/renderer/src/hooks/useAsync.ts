/**
 * Async data-fetching hook for the renderer.
 *
 * Wraps a promise-returning loader and exposes loading/error/data state
 * with a stable reload trigger. Cancellation-safe: a slow response can
 * never overwrite a newer one (reqId guard). Used by every screen so
 * loading/error/empty/data states are consistent (plan §8.2).
 *
 * The "start loading" transition happens during render rather than at the
 * top of the effect. It used to be `setLoading(true); setError(null)` inside
 * the effect body, which react-hooks 7 flags as `set-state-in-effect`: it
 * commits a frame still claiming the previous request's state, then
 * immediately re-renders. React's documented adjust-state-during-render
 * pattern reaches the same place in one pass, and is what the rule is
 * steering toward.
 *
 * Note that `data` deliberately survives a reload -- the previous result
 * stays on screen while the next one is in flight, rather than flashing an
 * empty state. Only `loading` and `error` reset.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly reload: () => void;
}

interface AsyncSnapshot<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
}

/** Shallow, positional comparison. Callers pass `[]` or `[someId]`. */
function sameInputs(a: readonly unknown[], b: readonly unknown[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((value, index) => Object.is(value, b[index]));
}

export function useAsync<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[] = [],
): AsyncState<T> {
  const [state, setState] = useState<AsyncSnapshot<T>>({
    data: null,
    loading: true,
    error: null,
  });
  const [tick, setTick] = useState(0);
  const reqIdRef = useRef(0);

  const inputs = [...deps, tick];
  const [seenInputs, setSeenInputs] = useState<readonly unknown[]>(inputs);
  if (!sameInputs(seenInputs, inputs)) {
    // Setting state during render of this same component is legal and does
    // not commit the in-progress frame -- React re-runs the body with the
    // new state before anything reaches the DOM.
    setSeenInputs(inputs);
    setState((prev) => ({ data: prev.data, loading: true, error: null }));
  }

  useEffect(() => {
    const reqId = ++reqIdRef.current;
    let cancelled = false;
    loader()
      .then((result) => {
        if (cancelled || reqId !== reqIdRef.current) return;
        setState((prev) => ({ ...prev, data: result }));
      })
      .catch((cause: unknown) => {
        if (cancelled || reqId !== reqIdRef.current) return;
        setState((prev) => ({
          ...prev,
          error: cause instanceof Error ? cause.message : String(cause),
        }));
      })
      .finally(() => {
        if (cancelled || reqId !== reqIdRef.current) return;
        setState((prev) => ({ ...prev, loading: false }));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  return { data: state.data, loading: state.loading, error: state.error, reload };
}
