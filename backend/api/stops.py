"""GET /api/stops, /api/stops/<id>, /api/routes, /api/routes/<id>.

The configured stops and routes from config/stops.yaml.

Response shapes: docs/api.md.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from backend.models import Stop
from backend.stops import StopNetwork

bp = Blueprint("stops", __name__)


def _network() -> StopNetwork:
    return current_app.config["NUWAY_CONFIG"].stops


def _stop_dict(network: StopNetwork, stop: Stop) -> dict:
    return {**stop.to_dict(), "routes": [route.id for route in network.routes_for_stop(stop.id)]}


def _not_found(code: str, kind: str, wanted: str, known) -> tuple:
    message = f"No {kind} with id '{wanted}'. Known ids: {', '.join(known) or 'none'}."
    return jsonify({"error": {"code": code, "message": message}}), 404


@bp.get("/api/stops")
def stops():
    """
    Every stop in file order, each with the ids of the routes it is on.
    """
    network = _network()
    return jsonify({"stops": [_stop_dict(network, stop) for stop in network.stops.values()]})


@bp.get("/api/stops/<stop_id>")
def stop(stop_id: str):
    """
    One stop. 404 `unknown_stop` if it is not configured.
    """
    network = _network()
    found = network.stop(stop_id)
    if found is None:
        return _not_found("unknown_stop", "stop", stop_id, network.stops)
    return jsonify(_stop_dict(network, found))


@bp.get("/api/routes")
def routes():
    """
    Every route in file order, with its stop ids in service order.
    """
    return jsonify({"routes": [route.to_dict() for route in _network().routes.values()]})


@bp.get("/api/routes/<route_id>")
def route(route_id: str):
    """
    One route with its stops in full, in service order. 404 `unknown_route`
    if it is not configured.
    """
    network = _network()
    found = network.route(route_id)
    if found is None:
        return _not_found("unknown_route", "route", route_id, network.routes)

    body = found.to_dict()
    del body["stop_ids"]
    body["stops"] = [_stop_dict(network, stop) for stop in network.stops_on_route(found.id)]
    return jsonify(body)
