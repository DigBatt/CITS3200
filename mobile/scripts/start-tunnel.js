#!/usr/bin/env node
// `npm run start:tunnel`: start Metro so Expo Go loads the app through the
// ngrok tunnel named in endpoints.yaml, and the app calls the tunnelled API.
// Extra arguments are passed to `expo start`.

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const YAML = require('yaml');

const file = path.join(__dirname, '..', 'endpoints.yaml');
const endpoints = YAML.parse(fs.readFileSync(file, 'utf8')) ?? {};
const tunnel = endpoints.tunnel ?? {};

for (const name of ['api', 'metro']) {
  if (typeof tunnel[name] !== 'string' || !/^https?:\/\//.test(tunnel[name])) {
    console.error(`endpoints.yaml: tunnel.${name} must be a URL, got ${JSON.stringify(tunnel[name])}`);
    process.exit(1);
  }
}

console.log(`Metro advertised at ${tunnel.metro}, app calls ${tunnel.api}`);
console.log('Make sure `ngrok start --all` is running (see ../ngrok/README.md).');

const result = spawnSync(process.platform === 'win32' ? 'npx.cmd' : 'npx', ['expo', 'start', ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: { ...process.env, NUWAY_TUNNEL: '1', EXPO_PACKAGER_PROXY_URL: tunnel.metro },
});
process.exit(result.status ?? 1);
