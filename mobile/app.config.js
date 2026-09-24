// Extends app.json with the endpoint mapping from endpoints.yaml, so the
// app can read it at runtime via Constants.expoConfig.extra.endpoints.
// NUWAY_TUNNEL=1 (set by `npm run start:tunnel`) selects the tunnel URLs.

const fs = require('fs');
const path = require('path');
const YAML = require('yaml');

function readEndpoints() {
  const file = path.join(__dirname, 'endpoints.yaml');
  if (!fs.existsSync(file)) return {};
  const parsed = YAML.parse(fs.readFileSync(file, 'utf8'));
  return parsed && typeof parsed === 'object' ? parsed : {};
}

module.exports = ({ config }) => {
  const endpoints = readEndpoints();
  return {
    ...config,
    extra: {
      ...config.extra,
      endpoints: {
        useTunnel: process.env.NUWAY_TUNNEL === '1',
        lan: endpoints.lan ?? {},
        tunnel: endpoints.tunnel ?? {},
      },
    },
  };
};
