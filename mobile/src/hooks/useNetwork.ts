import { useCallback, useEffect, useMemo, useState } from 'react';

import { getRoutes, getStops } from '@/api/client';
import type { Route, Stop } from '@/api/types';

export interface StopNetwork {
  stops: Stop[];
  routes: Route[];
  stopById: Map<string, Stop>;
  routeById: Map<string, Route>;
  /** A route's stops in service order, skipping any id the stops list lacks. */
  stopsOnRoute: (routeId: string) => Stop[];
  routeColour: (routeId: string) => string | null;
}

interface Loaded {
  attempt: number;
  stops: Stop[];
  routes: Route[];
  error: Error | null;
}

/** Stops and routes are configuration, so they load once and then stay. */
export function useNetwork() {
  // Bumping `attempt` re-runs the load; `loaded.attempt` lags it until the
  // fetch settles, which is what "loading" means here.
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded>({ attempt: -1, stops: [], routes: [], error: null });

  useEffect(() => {
    let cancelled = false;
    Promise.all([getStops(), getRoutes()])
      .then(([stopsBody, routesBody]) => {
        if (!cancelled) setLoaded({ attempt, stops: stopsBody.stops, routes: routesBody.routes, error: null });
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const error = caught instanceof Error ? caught : new Error(String(caught));
        setLoaded((current) => ({ ...current, attempt, error }));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const { stops, routes } = loaded;
  const network: StopNetwork = useMemo(() => {
    const stopById = new Map(stops.map((stop) => [stop.id, stop]));
    const routeById = new Map(routes.map((route) => [route.id, route]));
    return {
      stops,
      routes,
      stopById,
      routeById,
      stopsOnRoute: (routeId) =>
        (routeById.get(routeId)?.stop_ids ?? []).map((id) => stopById.get(id)).filter((stop): stop is Stop => Boolean(stop)),
      routeColour: (routeId) => routeById.get(routeId)?.colour ?? null,
    };
  }, [stops, routes]);

  return { network, error: loaded.error, loading: loaded.attempt !== attempt, reload };
}
