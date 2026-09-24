// The endpoint mapping from endpoints.yaml, as app.config.js exposes it.

import Constants from 'expo-constants';

export interface EndpointMap {
  useTunnel: boolean;
  lan: { port?: number };
  tunnel: { api?: string; metro?: string; dashboard?: string };
}

const EMPTY: EndpointMap = { useTunnel: false, lan: {}, tunnel: {} };

function asUrl(value: unknown): string | undefined {
  return typeof value === 'string' && /^https?:\/\//.test(value) ? value.replace(/\/+$/, '') : undefined;
}

/** What endpoints.yaml said when Metro started, with anything malformed dropped. */
export function endpointMap(): EndpointMap {
  const raw = Constants.expoConfig?.extra?.endpoints as Partial<EndpointMap> | undefined;
  if (!raw || typeof raw !== 'object') return EMPTY;
  const lanPort = Number(raw.lan?.port);
  return {
    useTunnel: raw.useTunnel === true,
    lan: Number.isInteger(lanPort) && lanPort > 0 ? { port: lanPort } : {},
    tunnel: {
      api: asUrl(raw.tunnel?.api),
      metro: asUrl(raw.tunnel?.metro),
      dashboard: asUrl(raw.tunnel?.dashboard),
    },
  };
}

/**
 * Where the Flask backend lives, in order of precedence:
 *
 * 1. EXPO_PUBLIC_API_URL from .env, for pointing anywhere at all.
 * 2. tunnel.api from endpoints.yaml when started with `npm run start:tunnel`.
 * 3. The Metro dev server's host on lan.port (or EXPO_PUBLIC_API_PORT), so a
 *    phone on the same Wi-Fi as the laptop reaches it with no configuration.
 */
export function apiBaseUrl(): string {
  const configured = process.env.EXPO_PUBLIC_API_URL;
  if (configured) return configured.replace(/\/+$/, '');

  const map = endpointMap();
  if (map.useTunnel && map.tunnel.api) return map.tunnel.api;

  const port = process.env.EXPO_PUBLIC_API_PORT ?? String(map.lan.port ?? 5000);
  const host = Constants.expoConfig?.hostUri?.split(':')[0];
  return `http://${host ?? '127.0.0.1'}:${port}`;
}
