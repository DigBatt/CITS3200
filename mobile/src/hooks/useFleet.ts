import { useMemo } from 'react';

import { getVehicles } from '@/api/client';
import type { Vehicle } from '@/api/types';

import { usePolling } from './usePolling';

const DEFAULT_REFRESH_SECONDS = 10;

export function refreshIntervalMs(): number {
  const raw = Number(process.env.EXPO_PUBLIC_REFRESH_SECONDS);
  const seconds = Number.isFinite(raw) && raw >= 2 ? raw : DEFAULT_REFRESH_SECONDS;
  return seconds * 1000;
}

/** The fleet's current state, re-fetched on an interval. */
export function useFleet() {
  const polled = usePolling(getVehicles, refreshIntervalMs());
  const vehicles: Vehicle[] = useMemo(() => polled.data?.vehicles ?? [], [polled.data]);
  return { ...polled, vehicles };
}
