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
