// Shapes from docs/api.md in the repo root. Keep in step with the backend.

export type VehicleStatus = 'active' | 'inactive';

export interface Position {
  vehicle_id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
  altitude_m: number | null;
  heading_deg: number | null;
  speed_mps: number | null;
  gps_status: number;
  battery_percent: number | null;
}

export interface Vehicle {
  id: string;
  name: string;
  colour: string;
  status: VehicleStatus;
  last_seen: string | null;
  seconds_since_last_seen: number | null;
  last_position: Position | null;
}

export interface VehiclesResponse {
  generated_at: string;
  inactivity_threshold_seconds: number;
  vehicles: Vehicle[];
}

export interface VehicleTrack {
  vehicle_id: string;
  name: string;
  colour: string;
  count: number;
  positions: Position[];
}

export interface PositionsResponse {
  from: string;
  to: string;
  vehicles: VehicleTrack[];
}

export interface Stop {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  routes: string[];
}

export interface StopsResponse {
  stops: Stop[];
}

export interface Route {
  id: string;
  name: string;
  colour: string | null;
  loop: boolean;
  stop_ids: string[];
}

export interface RoutesResponse {
  routes: Route[];
}

export type PickupStatus = 'open' | 'collected' | 'expired';

export interface PickupRequest {
  id: string;
  stop_id: string;
  status: PickupStatus;
  created_at: string;
  cleared_at: string | null;
}

export interface PickupRequestResponse {
  request: PickupRequest;
}

export interface PickupRequestsResponse {
  requests: PickupRequest[];
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}
