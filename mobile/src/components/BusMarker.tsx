import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { Marker } from 'react-native-maps';

import type { Vehicle } from '@/api/types';
import { formatAge, formatSpeed } from '@/lib/format';
import { hasFix } from '@/lib/geo';
import { colours } from '@/lib/theme';

interface Props {
  vehicle: Vehicle;
  onPress?: (vehicle: Vehicle) => void;
}

/**
 * A bus on the map, coloured as in the dashboard and greyed once the backend
 * says it is inactive. A small heading arrow shows which way it is going.
 *
 * Android snapshots custom marker views, so tracking is switched on briefly
 * whenever the look changes and off again to keep the map smooth.
 */
export function BusMarker({ vehicle, onPress }: Props) {
  const position = vehicle.last_position;
  const isActive = vehicle.status === 'active';
  const tint = isActive ? vehicle.colour : colours.inactive;
  const heading = position?.heading_deg ?? null;
  const lookKey = `${tint}:${Math.round((heading ?? 0) / 10)}`;

  // When the look changes, track view changes again until the next snapshot.
  const [track, setTrack] = useState(true);
  const [trackedKey, setTrackedKey] = useState(lookKey);
  if (trackedKey !== lookKey) {
    setTrackedKey(lookKey);
    setTrack(true);
  }
  useEffect(() => {
    if (!track) return;
    const timer = setTimeout(() => setTrack(false), 400);
    return () => clearTimeout(timer);
  }, [track, trackedKey]);

  if (!hasFix(position)) return null;

  return (
    <Marker
      coordinate={{ latitude: position.latitude, longitude: position.longitude }}
      title={vehicle.name}
      description={`${isActive ? formatSpeed(position.speed_mps) : 'Not reporting'} · seen ${formatAge(vehicle.seconds_since_last_seen)}`}
      anchor={{ x: 0.5, y: 0.5 }}
      tracksViewChanges={Platform.OS === 'android' ? track : false}
      onPress={() => onPress?.(vehicle)}
      zIndex={isActive ? 20 : 10}
    >
      <View style={styles.wrapper}>
        {heading != null && isActive ? (
          <View style={[styles.arrow, { transform: [{ rotate: `${heading}deg` }] }]}>
            <Ionicons name="caret-up" size={14} color={tint} style={styles.arrowIcon} />
          </View>
        ) : null}
        <View style={[styles.disc, { backgroundColor: tint }]}>
          <Ionicons name="bus" size={16} color="#ffffff" />
        </View>
      </View>
    </Marker>
  );
}

const SIZE = 30;
const ARROW_BOX = SIZE + 22;

const styles = StyleSheet.create({
  wrapper: { width: ARROW_BOX, height: ARROW_BOX, alignItems: 'center', justifyContent: 'center' },
  disc: {
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
    borderWidth: 2,
    borderColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 3,
  },
  arrow: { position: 'absolute', width: ARROW_BOX, height: ARROW_BOX, alignItems: 'center' },
  arrowIcon: { marginTop: -1 },
});
