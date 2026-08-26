"""
The storage interface.

Everything above this file is written against this and nothing else. Sprint 3
swaps CsvRepository for SqliteRepository.

    get_positions(vehicle_ids, start, end)  -> {vehicle_id: [Position]}
    get_events(vehicle_ids, start, end)     -> {vehicle_id: [Event]}
    get_latest_positions(vehicle_ids)       -> {vehicle_id: Position | None}

Contract: every requested id appears as a key, with an empty list where there
is no data. A vehicle with nothing to show must be distinguishable from one
that was not asked for.

get_latest_positions is separate because asking where is the fleet now is a
different question from where did it go on Tuesday, and an indexed
store answers it cheaper than a range scan.
"""
