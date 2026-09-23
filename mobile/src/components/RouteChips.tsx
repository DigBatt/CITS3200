import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';

import type { Route } from '@/api/types';
import { colours, radius, spacing } from '@/lib/theme';

interface Props {
  routes: Route[];
  selected: string | null;
  onSelect: (routeId: string | null) => void;
}

/** "All routes" plus one chip per route, like the dashboard's filter bar. */
export function RouteChips({ routes, selected, onSelect }: Props) {
  if (routes.length === 0) return null;

  const chip = (id: string | null, label: string, colour: string | null) => {
    const isActive = selected === id;
    const tint = colour ?? colours.routeFallback;
    return (
      <Pressable
        key={id ?? 'all'}
        onPress={() => onSelect(id)}
        accessibilityRole="button"
        accessibilityState={{ selected: isActive }}
        style={[styles.chip, isActive && { backgroundColor: tint, borderColor: tint }]}
      >
        <Text style={[styles.label, isActive && styles.labelActive]}>{label}</Text>
      </Pressable>
    );
  };

  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
      {chip(null, 'All routes', colours.text)}
      {routes.map((route) => chip(route.id, route.name, route.colour))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colours.border,
    backgroundColor: colours.surface,
  },
  label: { fontSize: 13, fontWeight: '600', color: colours.text },
  labelActive: { color: '#ffffff' },
});
