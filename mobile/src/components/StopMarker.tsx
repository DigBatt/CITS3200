import { StyleSheet, View } from 'react-native';
import { Marker } from 'react-native-maps';

import type { Stop } from '@/api/types';
import { colours } from '@/lib/theme';

interface Props {
  stop: Stop;
  routeNames: string[];
  /** The route the user picked, or null for all. Off-route stops fade. */
  selectedRouteId: string | null;
  routeColour: string | null;
  onCalloutPress?: (stop: Stop) => void;
}

export function StopMarker({ stop, routeNames, selectedRouteId, routeColour, onCalloutPress }: Props) {
  const onSelectedRoute = selectedRouteId !== null && stop.routes.includes(selectedRouteId);
  const dimmed = selectedRouteId !== null && !onSelectedRoute;
  const fill = onSelectedRoute ? (routeColour ?? colours.routeFallback) : colours.surface;
  const size = onSelectedRoute ? 16 : 12;

  return (
    <Marker
      key={`${stop.id}:${onSelectedRoute}:${dimmed}`}
      coordinate={{ latitude: stop.latitude, longitude: stop.longitude }}
      title={stop.name}
      description={routeNames.length ? `${routeNames.join(', ')} · tap to request pickup` : 'Not on any route'}
      anchor={{ x: 0.5, y: 0.5 }}
      opacity={dimmed ? 0.35 : 1}
      tracksViewChanges={false}
      onCalloutPress={() => onCalloutPress?.(stop)}
      zIndex={onSelectedRoute ? 5 : 1}
    >
      <View
        style={[
          styles.dot,
          { width: size, height: size, borderRadius: size / 2, backgroundColor: fill },
          onSelectedRoute ? styles.onRoute : styles.neutral,
        ]}
      />
    </Marker>
  );
}

const styles = StyleSheet.create({
  dot: { borderWidth: 2 },
  neutral: { borderColor: colours.text },
  onRoute: { borderColor: '#ffffff' },
});
