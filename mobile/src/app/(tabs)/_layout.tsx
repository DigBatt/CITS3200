import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';

import { colours } from '@/lib/theme';

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: colours.accent,
        tabBarInactiveTintColor: colours.muted,
        headerStyle: { backgroundColor: colours.surface },
        headerTitleStyle: { color: colours.text, fontWeight: '700' },
        headerShadowVisible: false,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Live map',
          headerShown: false,
          tabBarIcon: ({ color, size }) => <Ionicons name="map" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="request"
        options={{
          title: 'Request pickup',
          tabBarIcon: ({ color, size }) => <Ionicons name="hand-right" size={size} color={color} />,
        }}
      />
    </Tabs>
  );
}
