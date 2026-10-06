"""
Encoded polylines, the compact text form of a list of coordinates.

The format Google Maps, OSRM and most map tools share: each coordinate is
the difference from the previous one, scaled, zig-zag encoded and written as
printable characters. config/stops.json keeps paths as plain [lat, lon]
pairs; an older config/stops.yaml kept them this way, and is still read.

Precision 6 (about 0.1 m), not the usual 5 (about 1 m), so a path meets its
stop markers exactly.
"""

from __future__ import annotations
from typing import Iterable, Sequence

PRECISION = 6


def encode(points: Iterable[Sequence[float]], precision: int = PRECISION) -> str:
    """
    [(lat, lon), ...] as an encoded polyline.
    """
    factor = 10**precision
    out: list[str] = []
    last_lat = last_lon = 0
    for lat, lon in points:
        lat_i, lon_i = round(lat * factor), round(lon * factor)
        for delta in (lat_i - last_lat, lon_i - last_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last_lat, last_lon = lat_i, lon_i
    return "".join(out)


def decode(text: str, precision: int = PRECISION) -> list[tuple[float, float]]:
    """
    An encoded polyline as [(lat, lon), ...].

    Raises
    ------
    ValueError
        If the text is not an encoded polyline.
    """
    factor = 10**precision
    points: list[tuple[float, float]] = []
    index = lat = lon = 0
    while index < len(text):
        pair = []
        for _ in range(2):
            shift = result = 0
            while True:
                if index >= len(text):
                    raise ValueError("truncated polyline")
                byte = ord(text[index]) - 63
                if not 0 <= byte < 64:
                    raise ValueError(f"not a polyline character: {text[index]!r}")
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            pair.append(~(result >> 1) if result & 1 else result >> 1)
        lat += pair[0]
        lon += pair[1]
        points.append((lat / factor, lon / factor))
    return points
