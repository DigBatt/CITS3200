"""Shared query parameter parsing for read endpoints."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import request

from backend.models import parse_timestamp


class ApiParameterError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_vehicle_ids(config) -> list[str] | None:
    raw = (request.args.get("vehicles") or "").strip()
    if not raw:
        return None

    ids = list(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    known = {v.id for v in config.vehicles}
    unknown = [vehicle_id for vehicle_id in ids if vehicle_id not in known]
    if unknown:
        raise ApiParameterError(
            "unknown_vehicle",
            f"No vehicle with id '{unknown[0]}'. Known ids: {', '.join(sorted(known))}.",
        )
    return ids or None


def _is_bare_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _local_timezone(config):
    try:
        return ZoneInfo(config.timezone or "Australia/Perth")
    except Exception:
        return timezone(timedelta(hours=config.utc_offset_hours or 8))


def parse_range(config) -> tuple[datetime | None, datetime | None]:
    raw_from = (request.args.get("from") or "").strip()
    raw_to = (request.args.get("to") or "").strip()
    local_tz = _local_timezone(config)

    def parse_bound(raw: str, *, is_end: bool) -> datetime | None:
        if not raw:
            return None
        try:
            if _is_bare_date(raw):
                d = datetime.strptime(raw, "%Y-%m-%d").date()
                local = datetime.combine(d, time.max if is_end else time.min, tzinfo=local_tz)
                return local.astimezone(timezone.utc)
            return parse_timestamp(raw)
        except (ValueError, TypeError) as exc:
            raise ApiParameterError("bad_timestamp", f"Invalid timestamp '{raw}'.") from exc

    start = parse_bound(raw_from, is_end=False)
    end = parse_bound(raw_to, is_end=True)
    if start is not None and end is not None and start > end:
        raise ApiParameterError("bad_range", "The 'from' timestamp must not be after 'to'.")
    return start, end
