import { Polyline } from 'react-native-maps';

import type { StopNetwork } from '@/hooks/useNetwork';
import { colours } from '@/lib/theme';

interface Props {
  network: StopNetwork;
  selectedRouteId: string | null;
}

/**
 * Each route drawn stop to stop in service order, closed when it loops.
 * The stops file is the only geometry the backend has, so these are
 * straight legs rather than the road the shuttle actually drives.
 */
export function RouteLines({ network, selectedRouteId }: Props) {
  return (
    <>
      {network.routes.map((route) => {
        const stops = network.stopsOnRoute(route.id);
        if (stops.length < 2) return null;

        const coordinates = stops.map((stop) => ({ latitude: stop.latitude, longitude: stop.longitude }));
        if (route.loop) coordinates.push(coordinates[0]);

        const isSelected = selectedRouteId === route.id;
        const dimmed = selectedRouteId !== null && !isSelected;
        return (
          <Polyline
            key={route.id}
            coordinates={coordinates}
            strokeColor={route.colour ?? colours.routeFallback}
            strokeWidth={isSelected ? 5 : 3}
            lineDashPattern={dimmed ? [6, 8] : undefined}
            zIndex={isSelected ? 2 : 1}
          />
        );
      })}
    </>
  );
}
