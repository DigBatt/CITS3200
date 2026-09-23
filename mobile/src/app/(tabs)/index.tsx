import { useRouter } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import MapView, { Polyline } from 'react-native-maps';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { getPositions } from '@/api/client';
import type { Stop, Vehicle } from '@/api/types';
import { Banner } from '@/components/Banner';
import { BusMarker } from '@/components/BusMarker';
import { RouteChips } from '@/components/RouteChips';
import { RouteLines } from '@/components/RouteLines';
import { StopMarker } from '@/components/StopMarker';
import { VehicleCard } from '@/components/VehicleCard';
import { refreshIntervalMs, useFleet } from '@/hooks/useFleet';
import { useNetwork } from '@/hooks/useNetwork';
import { useNow } from '@/hooks/useNow';
import { usePolling } from '@/hooks/usePolling';
import { formatAge } from '@/lib/format';
import { CAMPUS_REGION, hasFix } from '@/lib/geo';
import { colours, radius, spacing } from '@/lib/theme';

/**
 * Screen 1: live bus positions with the configured stops and routes.
 * Vehicles are re-fetched on an interval; stops and routes load once.
 */
export default function LiveMapScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const mapRef = useRef<MapView>(null);

  const fleet = useFleet();
  const { network, error: networkError, reload: reloadNetwork } = useNetwork();

  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [showStops, setShowStops] = useState(true);
  const [showTrails, setShowTrails] = useState(false);

  // Today's stored positions, only fetched while the trails toggle is on.
  const trails = usePolling(() => getPositions(), refreshIntervalMs() * 4, showTrails);

  // Keeps "updated 12 s ago" counting between polls.
  const now = useNow();

  const routeNamesFor = useCallback(
    (stop: Stop) => network.routes.filter((route) => stop.routes.includes(route.id)).map((route) => route.name),
    [network.routes],
  );

  const focusVehicle = useCallback((vehicle: Vehicle) => {
    const position = vehicle.last_position;
    if (!hasFix(position)) return;
    mapRef.current?.animateToRegion(
      { latitude: position.latitude, longitude: position.longitude, latitudeDelta: 0.005, longitudeDelta: 0.004 },
      400,
    );
  }, []);

  const requestAt = useCallback(
    (stop: Stop) => router.push({ pathname: '/request', params: { stop: stop.id } }),
    [router],
  );

  const trailLines = useMemo(() => {
    if (!showTrails || !trails.data) return null;
    return trails.data.vehicles.map((track) => {
      const coordinates = track.positions
        .filter(hasFix)
        .map((position) => ({ latitude: position.latitude, longitude: position.longitude }));
      if (coordinates.length < 2) return null;
      return <Polyline key={track.vehicle_id} coordinates={coordinates} strokeColor={track.colour} strokeWidth={2} />;
    });
  }, [showTrails, trails.data]);

  const updatedAge = fleet.updatedAt ? Math.max(0, now - fleet.updatedAt) / 1000 : null;
  const fleetError = fleet.error && !fleet.data ? fleet.error : null;

  return (
    <View style={styles.screen}>
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        initialRegion={CAMPUS_REGION}
        showsUserLocation
        showsMyLocationButton={false}
        showsCompass={false}
        toolbarEnabled={false}
      >
        {trailLines}
        <RouteLines network={network} selectedRouteId={selectedRouteId} />
        {showStops
          ? network.stops.map((stop) => (
              <StopMarker
                key={stop.id}
                stop={stop}
                routeNames={routeNamesFor(stop)}
                selectedRouteId={selectedRouteId}
                routeColour={selectedRouteId ? network.routeColour(selectedRouteId) : null}
                onCalloutPress={requestAt}
              />
            ))
          : null}
        {fleet.vehicles.map((vehicle) => (
          <BusMarker key={vehicle.id} vehicle={vehicle} onPress={focusVehicle} />
        ))}
      </MapView>

      <View style={[styles.top, { paddingTop: insets.top + spacing.sm }]} pointerEvents="box-none">
        <View style={styles.panel}>
          <RouteChips routes={network.routes} selected={selectedRouteId} onSelect={setSelectedRouteId} />
          <View style={styles.toggles}>
            <Toggle label="Stops" value={showStops} onChange={setShowStops} />
            <Toggle label="Today's trails" value={showTrails} onChange={setShowTrails} />
          </View>
        </View>
        {fleetError ? (
          <Banner tone="error" message={fleetError.message} actionLabel="Retry" onAction={() => void fleet.refresh()} />
        ) : null}
        {networkError ? (
          <Banner tone="error" message={`Stops unavailable: ${networkError.message}`} actionLabel="Retry" onAction={reloadNetwork} />
        ) : null}
        {fleet.error && fleet.data ? <Banner tone="info" message={`Showing last good update. ${fleet.error.message}`} /> : null}
      </View>

      <View style={[styles.bottom, { paddingBottom: spacing.sm }]} pointerEvents="box-none">
        <View style={styles.statusRow}>
          <Text style={styles.statusText}>
            {fleet.loading
              ? 'Loading fleet…'
              : `${fleet.vehicles.filter((v) => v.status === 'active').length} of ${fleet.vehicles.length} live · updated ${formatAge(updatedAge)}`}
          </Text>
          <Pressable onPress={() => mapRef.current?.animateToRegion(CAMPUS_REGION, 400)} hitSlop={8}>
            <Text style={styles.link}>Campus</Text>
          </Pressable>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.cards}>
          {fleet.vehicles.map((vehicle) => (
            <VehicleCard key={vehicle.id} vehicle={vehicle} compact onPress={() => focusVehicle(vehicle)} />
          ))}
        </ScrollView>
      </View>
    </View>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (next: boolean) => void }) {
  return (
    <View style={styles.toggle}>
      <Text style={styles.toggleLabel}>{label}</Text>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: colours.accent }} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colours.background },
  top: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: spacing.md, gap: spacing.sm },
  panel: {
    backgroundColor: 'rgba(255,255,255,0.94)',
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colours.border,
    paddingBottom: spacing.xs,
  },
  toggles: { flexDirection: 'row', gap: spacing.lg, paddingHorizontal: spacing.lg, paddingBottom: spacing.xs },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  toggleLabel: { fontSize: 13, color: colours.text, fontWeight: '600' },
  bottom: { position: 'absolute', bottom: 0, left: 0, right: 0, gap: spacing.sm },
  statusRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginHorizontal: spacing.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(255,255,255,0.94)',
    borderWidth: 1,
    borderColor: colours.border,
  },
  statusText: { fontSize: 12, color: colours.muted },
  link: { fontSize: 12, fontWeight: '700', color: colours.accent },
  cards: { paddingHorizontal: spacing.lg, gap: spacing.sm },
});
