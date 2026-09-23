import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

export interface Polled<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  updatedAt: number | null;
  refresh: () => Promise<void>;
}

/**
 * Call `fetcher` now and every `intervalMs` while the app is in the
 * foreground. The last good result stays on screen through a failed poll,
 * with the error alongside it, so a flaky network never blanks the map.
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, enabled = true): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error(String(caught)));
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer) return;
      void refresh();
      timer = setInterval(() => void refresh(), intervalMs);
    };
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };

    start();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') start();
      else stop();
    });
    return () => {
      stop();
      subscription.remove();
    };
  }, [enabled, intervalMs, refresh]);

  return { data, error, loading, updatedAt, refresh };
}
