import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { ApiError, createPickupRequest, getPickupRequests } from '@/api/client';
import type { PickupRequest } from '@/api/types';

interface PickupRequestsValue {
  /** Requests made from this app since it was opened, newest first. */
  mine: PickupRequest[];
  submit: (stopId: string) => Promise<{ request: PickupRequest; created: boolean }>;
  refresh: () => Promise<void>;
}

const PickupRequestsContext = createContext<PickupRequestsValue | null>(null);

/**
 * The backend identifies a rider by a cookie it sets on the first request,
 * which the native cookie jar keeps for us. What it does not offer is "my
 * requests", so the ones made here are remembered in memory and their status
 * refreshed from the operator listing by id.
 */
export function PickupRequestsProvider({ children }: { children: ReactNode }) {
  const [mine, setMine] = useState<PickupRequest[]>([]);

  const submit = useCallback(async (stopId: string) => {
    let body;
    try {
      body = await createPickupRequest(stopId);
    } catch (caught) {
      // A backend without the endpoint answers 404, or 405 when its static
      // file route swallows the path for GET only.
      if (caught instanceof ApiError && (caught.status === 404 || caught.status === 405)) {
        throw new ApiError(
          'not_available',
          'This server does not accept pickup requests yet. It needs the /api/pickup-requests endpoint.',
          404,
        );
      }
      throw caught;
    }
    const { request } = body;
    let created = true;
    setMine((current) => {
      created = !current.some((existing) => existing.id === request.id);
      return [request, ...current.filter((existing) => existing.id !== request.id)];
    });
    return { request, created };
  }, []);

  const refresh = useCallback(async () => {
    if (mine.length === 0) return;
    const { requests } = await getPickupRequests();
    const byId = new Map(requests.map((request) => [request.id, request]));
    setMine((current) => current.map((request) => byId.get(request.id) ?? request));
  }, [mine.length]);

  const value = useMemo(() => ({ mine, submit, refresh }), [mine, submit, refresh]);
  return <PickupRequestsContext.Provider value={value}>{children}</PickupRequestsContext.Provider>;
}

export function usePickupRequests(): PickupRequestsValue {
  const value = useContext(PickupRequestsContext);
  if (!value) throw new Error('usePickupRequests needs a PickupRequestsProvider above it');
  return value;
}
