// Fetch wrappers for the dashboard's JSON API (docs/api.md). Mirrors
// frontend/js/api.js, plus the pickup request endpoint. The base URL comes
// from endpoints.yaml, see src/lib/endpoints.ts.

import { apiBaseUrl } from '@/lib/endpoints';

import type {
  ApiErrorBody,
  PickupRequestResponse,
  PickupRequestsResponse,
  PositionsResponse,
  RoutesResponse,
  StopsResponse,
  VehiclesResponse,
} from './types';

export { apiBaseUrl };

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

interface RequestOptions {
  query?: Record<string, string | undefined>;
  method?: 'GET' | 'POST';
  body?: unknown;
}

async function request<T>(path: string, { query, method = 'GET', body }: RequestOptions = {}): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value) params.set(key, value);
  }
  const suffix = params.toString();
  const url = `${apiBaseUrl()}${path}${suffix ? `?${suffix}` : ''}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      // Native fetch keeps the backend's rider_token cookie between calls.
      credentials: 'include',
    });
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new ApiError('network', `Cannot reach ${apiBaseUrl()} (${reason})`, 0);
  }

  const parsed = (await response.json().catch(() => null)) as (T & Partial<ApiErrorBody>) | null;

  if (!response.ok) {
    const code = parsed?.error?.code ?? (response.status === 404 ? 'not_found' : 'http_error');
    const message = parsed?.error?.message ?? `Request failed (${response.status})`;
    throw new ApiError(code, message, response.status);
  }
  if (parsed === null) {
    throw new ApiError('bad_response', `${path} did not return JSON`, response.status);
  }
  return parsed;
}

export function getVehicles(): Promise<VehiclesResponse> {
  return request('/api/vehicles');
}

export function getPositions(query: { vehicles?: string; from?: string; to?: string } = {}): Promise<PositionsResponse> {
  return request('/api/positions', { query });
}

export function getStops(): Promise<StopsResponse> {
  return request('/api/stops');
}

export function getRoutes(): Promise<RoutesResponse> {
  return request('/api/routes');
}

export function createPickupRequest(stopId: string): Promise<PickupRequestResponse> {
  return request('/api/pickup-requests', { method: 'POST', body: { stop_id: stopId } });
}

export function getPickupRequests(status?: 'open' | 'collected' | 'expired'): Promise<PickupRequestsResponse> {
  return request('/api/pickup-requests', { query: { status } });
}
