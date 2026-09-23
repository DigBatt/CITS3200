export interface LatLng {
  latitude: number;
  longitude: number;
}

// UWA Crawley, matching map.centre in config/app.yaml.
export const CAMPUS_CENTRE: LatLng = { latitude: -31.98133, longitude: 115.81597 };

export const CAMPUS_REGION = {
  ...CAMPUS_CENTRE,
  latitudeDelta: 0.014,
  longitudeDelta: 0.012,
};

const EARTH_RADIUS_M = 6_371_000;

/** Great-circle distance in metres. */
export function distanceMetres(a: LatLng, b: LatLng): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);

  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

type MaybeFix = { latitude: number | null; longitude: number | null };

/** True when a position has both coordinates, narrowing them to numbers. */
export function hasFix<T extends MaybeFix>(position: T | null | undefined): position is T & LatLng {
  return position != null && position.latitude != null && position.longitude != null;
}
