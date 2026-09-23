import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { PickupRequestsProvider } from '@/hooks/usePickupRequests';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <PickupRequestsProvider>
        <StatusBar style="dark" />
        <Stack>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        </Stack>
      </PickupRequestsProvider>
    </SafeAreaProvider>
  );
}
