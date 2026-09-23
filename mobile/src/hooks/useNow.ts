import { useSyncExternalStore } from 'react';

/**
 * The current time, re-read every `intervalMs`, for relative labels such as
 * "seen 12 s ago" that should keep counting between polls. Reading the
 * clock through an external store keeps render pure.
 */
export function useNow(intervalMs = 5000): number {
  return useSyncExternalStore(
    (onChange) => {
      const timer = setInterval(onChange, intervalMs);
      return () => clearInterval(timer);
    },
    () => Math.floor(Date.now() / 1000) * 1000,
    () => Math.floor(Date.now() / 1000) * 1000,
  );
}
