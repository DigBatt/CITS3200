import { StyleSheet, Text, View } from 'react-native';

import type { VehicleStatus } from '@/api/types';
import { colours, radius } from '@/lib/theme';

export function StatusPill({ status }: { status: VehicleStatus }) {
  const isActive = status === 'active';
  return (
    <View style={[styles.pill, { backgroundColor: isActive ? colours.activeSoft : colours.inactiveSoft }]}>
      <View style={[styles.dot, { backgroundColor: isActive ? colours.active : colours.inactive }]} />
      <Text style={[styles.text, { color: isActive ? colours.active : colours.muted }]}>
        {isActive ? 'Live' : 'Not reporting'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  dot: { width: 7, height: 7, borderRadius: 4 },
  text: { fontSize: 12, fontWeight: '600' },
});
