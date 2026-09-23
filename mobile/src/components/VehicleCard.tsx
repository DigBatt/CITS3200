import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Vehicle } from '@/api/types';
import { formatAge, formatSpeed } from '@/lib/format';
import { colours, radius, spacing } from '@/lib/theme';

import { StatusPill } from './StatusPill';

interface Props {
  vehicle: Vehicle;
  /** Extra line under the stats, such as distance to a chosen stop. */
  note?: string;
  onPress?: () => void;
  compact?: boolean;
}

export function VehicleCard({ vehicle, note, onPress, compact = false }: Props) {
  const position = vehicle.last_position;
  const isActive = vehicle.status === 'active';
  const tint = isActive ? vehicle.colour : colours.inactive;

  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      style={({ pressed }) => [styles.card, compact && styles.compact, pressed && styles.pressed]}
    >
      <View style={styles.header}>
        <View style={[styles.swatch, { backgroundColor: tint }]} />
        <Text style={styles.name} numberOfLines={1}>
          {vehicle.name}
        </Text>
        <StatusPill status={vehicle.status} />
      </View>
      <View style={styles.stats}>
        <Stat label="Seen" value={formatAge(vehicle.seconds_since_last_seen)} />
        <Stat label="Speed" value={isActive ? formatSpeed(position?.speed_mps) : '–'} />
        {position?.battery_percent != null ? <Stat label="Battery" value={`${position.battery_percent}%`} /> : null}
      </View>
      {note ? (
        <Text style={styles.note} numberOfLines={1}>
          {note}
        </Text>
      ) : null}
    </Pressable>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colours.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colours.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  compact: { width: 220 },
  pressed: { opacity: 0.85 },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  swatch: { width: 12, height: 12, borderRadius: 6 },
  name: { flex: 1, fontSize: 15, fontWeight: '700', color: colours.text },
  stats: { flexDirection: 'row', gap: spacing.lg },
  stat: { gap: 2 },
  statLabel: { fontSize: 11, color: colours.muted, textTransform: 'uppercase', letterSpacing: 0.4 },
  statValue: { fontSize: 14, fontWeight: '600', color: colours.text },
  note: { fontSize: 12, color: colours.muted },
});
