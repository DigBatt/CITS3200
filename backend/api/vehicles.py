"""GET /api/vehicles.

The fleet, its identity and its current state.

Liveness is decided here, on the server, from config/app.yaml. The browser is
told the answer and the threshold, but never decides for itself.

Response shape: docs/api.md.
"""
