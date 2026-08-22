/**
 * Async data-fetching hook for the renderer.
 *
 * Wraps a promise-returning loader and exposes loading/error/data state
 * with a stable reload trigger. Cancellation-safe: a slow response can
 * never overwrite a newer one (reqId guard). Used by every screen so
 * loading/error/empty/data states are consistent (plan §8.2).
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly reload: () => void;
}

export function useAsync<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reqIdRef = useRef(0);

  useEffect(() => {
    const reqId = ++reqIdRef.current;
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((result) => {
        if (cancelled || reqId !== reqIdRef.current) return;
        setData(result);
      })
      .catch((cause: unknown) => {
        if (cancelled || reqId !== reqIdRef.current) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (cancelled || reqId !== reqIdRef.current) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  return { data, loading, error, reload };
}
