"""
Shared query parameter parsing for the read endpoints.

The rules are specified in docs/api.md:

    ?vehicles=1,2   absent or empty means the whole fleet; unknown id is 400
    ?from= &to=     an ISO 8601 instant, or a bare date meaning that whole
                    day in Australia/Perth (a user picking a day from a
                    calendar means their day, not a UTC day)

Also owns the error shape: {"error": {"code", "message"}} with codes
bad_timestamp, bad_range, unknown_vehicle, data_unavailable.
"""


from datetime import datetime, time

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

PERTH_TZ = ZoneInfo("Australia/Perth")
UTC_TZ = ZoneInfo("UTC")


def perth_date_to_utc_range(date_string):
    date = datetime.strptime(date_string, "%Y-%m-%d").date()

    start_perth = datetime.combine(date, time.min, tzinfo=PERTH_TZ)
    end_perth = datetime.combine(date, time.max, tzinfo=PERTH_TZ)

    start_utc = start_perth.astimezone(UTC_TZ)
    end_utc = end_perth.astimezone(UTC_TZ)

    return start_utc, end_utc

def parse_time_value(value):
    # bare date: YYYY-MM-DD
    if len(value) == 10:
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return "date", value
        except ValueError:
            pass

    # ISO 8601 timestamp
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "timestamp", parsed
    except ValueError:
        raise ValueError("bad_timestamp")

def parse_time_bound(value, is_start):
    value_type, parsed = parse_time_value(value)

    if value_type == "date":
        start_utc, end_utc = perth_date_to_utc_range(parsed)

        if is_start:
            return start_utc
        else:
            return end_utc

    # Full ISO 8601 timestamp must contain timezone information
    if parsed.tzinfo is None:
        raise ValueError("bad_timestamp")

    return parsed.astimezone(UTC_TZ)

def parse_time_range(from_value, to_value):
    start = parse_time_bound(from_value, True)
    end = parse_time_bound(to_value, False)

    if start > end:
        raise ValueError("bad_range")

    return start, end

def parse_vehicle_ids(value, known_ids):
    known_ids = list(known_ids)

    # Missing or empty parameter means the whole fleet
    if value is None or value.strip() == "":
        return known_ids

    vehicle_ids = [vehicle_id.strip() for vehicle_id in value.split(",")]

    for vehicle_id in vehicle_ids:
        if vehicle_id not in known_ids:
            raise ValueError("unknown_vehicle")

    return vehicle_ids