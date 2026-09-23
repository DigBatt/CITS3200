import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colours, radius, spacing } from '@/lib/theme';

interface Props {
  tone?: 'error' | 'info';
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function Banner({ tone = 'info', message, actionLabel, onAction }: Props) {
  const isError = tone === 'error';
  return (
    <View style={[styles.banner, isError ? styles.error : styles.info]}>
      <Text style={[styles.text, isError && styles.errorText]} numberOfLines={3}>
        {message}
      </Text>
      {actionLabel && onAction ? (
        <Pressable onPress={onAction} hitSlop={8}>
          <Text style={[styles.action, isError && styles.errorText]}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
  },
  info: { backgroundColor: colours.accentSoft, borderColor: colours.accent },
  error: { backgroundColor: colours.dangerSoft, borderColor: colours.danger },
  text: { flex: 1, color: colours.text, fontSize: 13 },
  errorText: { color: colours.danger },
  action: { fontWeight: '600', fontSize: 13, color: colours.accent },
});
