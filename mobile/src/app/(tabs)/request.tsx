import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PickupRequest, Stop, Vehicle } from '@/api/types';
import { Banner } from '@/components/Banner';
import { RouteChips } from '@/components/RouteChips';
import { VehicleCard } from '@/components/VehicleCard';
import { useFleet } from '@/hooks/useFleet';
import { useNetwork } from '@/hooks/useNetwork';
import { useNow } from '@/hooks/useNow';
import { usePickupRequests } from '@/hooks/usePickupRequests';
import { ageSince, formatAge, formatClock, formatDistance } from '@/lib/format';
import { distanceMetres, hasFix } from '@/lib/geo';
import { colours, radius, spacing } from '@/lib/theme';

/**
 * Screen 2: the fleet as a list with live positions and route data, and a
 * stop picker that opens a pickup request against the backend.
 */
export default function RequestPickupScreen() {
  const params = useLocalSearchParams<{ stop?: string }>();
  const fleet = useFleet();
  const { network, error: networkError, loading: networkLoading, reload: reloadNetwork } = useNetwork();
  const pickups = usePickupRequests();

  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<{ tone: 'info' | 'error'; message: string } | null>(null);

  // Arriving from a stop callout on the map preselects that stop. State is
  // adjusted during render so a repeat visit with the same stop is a no-op.
  const [seenParam, setSeenParam] = useState(params.stop);
  if (params.stop !== seenParam) {
    setSeenParam(params.stop);
    if (params.stop) {
      setSelectedStopId(params.stop);
      setOutcome(null);
    }
  }
  const now = useNow();

  const stopsShown: Stop[] = useMemo(
    () => (selectedRouteId ? network.stopsOnRoute(selectedRouteId) : network.stops),
    [network, selectedRouteId],
  );
  const selectedStop = selectedStopId ? (network.stopById.get(selectedStopId) ?? null) : null;

  const distanceTo = useCallback(
    (vehicle: Vehicle): number | null => {
      const position = vehicle.last_position;
      if (!selectedStop || vehicle.status !== 'active' || !hasFix(position)) return null;
      return distanceMetres(position, selectedStop);
    },
    [selectedStop],
  );

  const nearest = useMemo(() => {
    let best: { vehicle: Vehicle; metres: number } | null = null;
    for (const vehicle of fleet.vehicles) {
      const metres = distanceTo(vehicle);
      if (metres !== null && (best === null || metres < best.metres)) best = { vehicle, metres };
    }
    return best;
  }, [fleet.vehicles, distanceTo]);

  const submit = useCallback(async () => {
    if (!selectedStop) return;
    setSubmitting(true);
    setOutcome(null);
    try {
      const { request, created } = await pickups.submit(selectedStop.id);
      setOutcome({
        tone: 'info',
        message: created
          ? `Pickup requested at ${selectedStop.name}. Reference ${shortId(request.id)}.`
          : `You already have an open request at ${selectedStop.name} (reference ${shortId(request.id)}).`,
      });
    } catch (caught) {
      setOutcome({ tone: 'error', message: caught instanceof Error ? caught.message : String(caught) });
    } finally {
      setSubmitting(false);
    }
  }, [pickups, selectedStop]);

  const refreshAll = useCallback(async () => {
    await Promise.all([fleet.refresh(), pickups.refresh().catch(() => undefined)]);
  }, [fleet, pickups]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={false} onRefresh={() => void refreshAll()} />}
      keyboardShouldPersistTaps="handled"
    >
      <Section title="Buses now" aside={fleet.updatedAt ? `updated ${formatAge(Math.max(0, now - fleet.updatedAt) / 1000)}` : undefined}>
        {fleet.error && !fleet.data ? (
          <Banner tone="error" message={fleet.error.message} actionLabel="Retry" onAction={() => void fleet.refresh()} />
        ) : null}
        {fleet.loading && !fleet.data ? <ActivityIndicator color={colours.accent} /> : null}
        {fleet.vehicles.map((vehicle) => {
          const metres = distanceTo(vehicle);
          return (
            <VehicleCard
              key={vehicle.id}
              vehicle={vehicle}
              note={metres !== null && selectedStop ? `${formatDistance(metres)} from ${selectedStop.name}` : undefined}
            />
          );
        })}
      </Section>

      <Section title="Route">
        {networkError ? (
          <Banner tone="error" message={networkError.message} actionLabel="Retry" onAction={reloadNetwork} />
        ) : null}
        {networkLoading ? <ActivityIndicator color={colours.accent} /> : null}
        <RouteChips routes={network.routes} selected={selectedRouteId} onSelect={setSelectedRouteId} />
        {selectedRouteId ? (
          <Text style={styles.hint}>
            {network.routeById.get(selectedRouteId)?.loop ? 'Loop service. ' : ''}
            Stops listed in service order.
          </Text>
        ) : null}
      </Section>

      <Section title="Stop">
        {stopsShown.length === 0 && !networkLoading ? <Text style={styles.hint}>No stops configured.</Text> : null}
        {stopsShown.map((stop, index) => {
          const isSelected = stop.id === selectedStopId;
          const names = network.routes.filter((route) => stop.routes.includes(route.id)).map((route) => route.name);
          return (
            <Pressable
              key={stop.id}
              onPress={() => {
                setSelectedStopId(stop.id);
                setOutcome(null);
              }}
              accessibilityRole="radio"
              accessibilityState={{ selected: isSelected }}
              style={[styles.stopRow, isSelected && styles.stopRowSelected]}
            >
              <View style={[styles.stopIndex, isSelected && styles.stopIndexSelected]}>
                <Text style={[styles.stopIndexText, isSelected && styles.stopIndexTextSelected]}>
                  {selectedRouteId ? index + 1 : '•'}
                </Text>
              </View>
              <View style={styles.stopBody}>
                <Text style={styles.stopName}>{stop.name}</Text>
                <Text style={styles.stopRoutes}>{names.length ? names.join(', ') : 'Not on any route'}</Text>
              </View>
              {isSelected ? <Ionicons name="checkmark-circle" size={22} color={colours.accent} /> : null}
            </Pressable>
          );
        })}
      </Section>

      <View style={styles.submitBox}>
        {selectedStop ? (
          <Text style={styles.nearest}>
            {nearest
              ? `Nearest live bus: ${nearest.vehicle.name}, ${formatDistance(nearest.metres)} away.`
              : 'No bus is reporting a position right now.'}
          </Text>
        ) : (
          <Text style={styles.nearest}>Choose a stop to request a pickup.</Text>
        )}
        <Pressable
          onPress={() => void submit()}
          disabled={!selectedStop || submitting}
          accessibilityRole="button"
          style={({ pressed }) => [styles.submit, (!selectedStop || submitting) && styles.submitDisabled, pressed && styles.pressed]}
        >
          {submitting ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.submitText}>{selectedStop ? `Request pickup at ${selectedStop.name}` : 'Request pickup'}</Text>
          )}
        </Pressable>
        {outcome ? <Banner tone={outcome.tone} message={outcome.message} /> : null}
      </View>

      {pickups.mine.length > 0 ? (
        <Section title="Your requests" aside="this session">
          {pickups.mine.map((request) => (
            <RequestRow key={request.id} request={request} now={now} stopName={network.stopById.get(request.stop_id)?.name ?? request.stop_id} />
          ))}
        </Section>
      ) : null}
    </ScrollView>
  );
}

function Section({ title, aside, children }: { title: string; aside?: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {aside ? <Text style={styles.sectionAside}>{aside}</Text> : null}
      </View>
      {children}
    </View>
  );
}

function RequestRow({ request, stopName, now }: { request: PickupRequest; stopName: string; now: number }) {
  const isOpen = request.status === 'open';
  return (
    <View style={styles.requestRow}>
      <View style={styles.stopBody}>
        <Text style={styles.stopName}>{stopName}</Text>
        <Text style={styles.stopRoutes}>
          {formatClock(request.created_at)} · {formatAge(ageSince(request.created_at, now))} · ref {shortId(request.id)}
        </Text>
      </View>
      <View style={[styles.statusTag, { backgroundColor: isOpen ? colours.activeSoft : colours.inactiveSoft }]}>
        <Text style={[styles.statusTagText, { color: isOpen ? colours.active : colours.muted }]}>{request.status}</Text>
      </View>
    </View>
  );
}

function shortId(id: string): string {
  return id.slice(0, 8).toUpperCase();
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colours.background },
  content: { padding: spacing.lg, gap: spacing.xl, paddingBottom: spacing.xl * 2 },
  section: { gap: spacing.sm },
  sectionHeader: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  sectionTitle: { fontSize: 17, fontWeight: '700', color: colours.text },
  sectionAside: { fontSize: 12, color: colours.muted },
  hint: { fontSize: 13, color: colours.muted, paddingHorizontal: spacing.xs },
  stopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: colours.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colours.border,
  },
  stopRowSelected: { borderColor: colours.accent, backgroundColor: colours.accentSoft },
  stopIndex: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colours.inactiveSoft,
  },
  stopIndexSelected: { backgroundColor: colours.accent },
  stopIndexText: { fontSize: 13, fontWeight: '700', color: colours.muted },
  stopIndexTextSelected: { color: '#ffffff' },
  stopBody: { flex: 1, gap: 2 },
  stopName: { fontSize: 15, fontWeight: '600', color: colours.text },
  stopRoutes: { fontSize: 12, color: colours.muted },
  submitBox: { gap: spacing.sm },
  nearest: { fontSize: 13, color: colours.muted, textAlign: 'center' },
  submit: {
    backgroundColor: colours.accent,
    borderRadius: radius.lg,
    paddingVertical: 14,
    alignItems: 'center',
    minHeight: 50,
    justifyContent: 'center',
  },
  submitDisabled: { backgroundColor: colours.inactive },
  pressed: { opacity: 0.85 },
  submitText: { color: '#ffffff', fontSize: 16, fontWeight: '700' },
  requestRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: colours.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colours.border,
  },
  statusTag: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  statusTagText: { fontSize: 12, fontWeight: '600', textTransform: 'capitalize' },
});
