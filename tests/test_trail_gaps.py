"""
A bus's trail is broken where it stopped reporting for longer than the
inactivity threshold, rather than joined across the silence by a straight
line. Driven in a real browser, as test_bus_markers.py, whose fixtures these
share.
"""

from __future__ import annotations

from tests.test_bus_markers import browser, page, server  # noqa: F401 - pytest fixtures

# Fixes every 6 seconds for a minute, an hour of silence, then a minute more
# somewhere else.
DRAW = """
({ gapSeconds }) => {
  const fix = (seconds, latitude) => ({
    timestamp: new Date(Date.UTC(2025, 8, 4, 2, 0, seconds)).toISOString(),
    latitude,
    longitude: 115.816,
  });
  const positions = [];
  for (let i = 0; i <= 10; i += 1) positions.push(fix(i * 6, -31.98 + i * 0.0001));
  for (let i = 0; i <= 10; i += 1) positions.push(fix(3660 + i * 6, -31.97 + i * 0.0001));

  drawTracks([{ vehicle_id: '1', name: 'nUWAy 1', count: positions.length, positions }], { fit: false, gapSeconds });

  const trail = layers.trails.getLayers().find((layer) => layer instanceof L.Polyline);
  const runs = trail.getLatLngs();
  return Array.isArray(runs[0]) ? runs.map((run) => run.length) : [runs.length];
}
"""


def test_trail_is_broken_at_a_silence_longer_than_the_threshold(page):
    assert page.evaluate(DRAW, {"gapSeconds": 300}) == [11, 11]


def test_trail_is_unbroken_within_the_threshold(page):
    # The hour of silence is inside a two hour threshold.
    assert page.evaluate(DRAW, {"gapSeconds": 7200}) == [22]


def test_trail_is_unbroken_without_a_threshold(page):
    assert page.evaluate(DRAW, {"gapSeconds": None}) == [22]


def test_the_map_is_given_the_servers_inactivity_threshold(page):
    # liveness.inactivity_threshold_seconds in config/app.yaml.
    assert page.evaluate("Vehicles.inactivityThreshold()") == 300
