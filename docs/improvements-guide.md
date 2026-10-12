# Improvements guide

Recommendations for project continuation - a future CITS3200
group, a contractor, or the client's own developers - on what is worth
improving and why. Each item below names where the current limitation lives
in the code or the vehicle hardware, so the next team does not have to
rediscover it from scratch.

These are not bugs in the delivered system; everything below works as
documented. They are the gaps the team ran out of time to close, or that
depend on something outside this repository (the shuttle's onboard unit, or
the calendar provider).

## 1. ROS web service and disengagement events

Each shuttle's only live feed is REV's tracking endpoint
(`gps_pos<n>.php`, mapped in `backend/ingest/rev_php.py`), which returns
exactly `{lat, lon, heading, battery_percentage, timestamp}`. There is no
field for autonomous-mode state or disengagement events, so neither the
dashboard nor the utilisation figures can show or record them, even though
that data matters at least as much as position for a safety case.

**Recommendation.** Work with REV to extend the same JSON packet the position
already comes through - the logger already polls it on a timer
(`logger.poll_interval_seconds`) and would need no new connection, just a
richer one. Once fields such as `autonomous` and a disengagement reason/time
exist, extend `rev_php.py`'s mapping and the position schema
(`docs/data-schema.md`) to carry them through, so the dashboard and the
utilisation model can report on them like any other field.

## 2. iCal subscription

The driving roster syncs from one specific vendor's proprietary API
(`api.calendar.online/event`, in `backend/roster_sync.py`), authenticated by
nothing more than a link id (`calendar_online_id` in `secrets.yaml`). The
schedule-to-dashboard link depends entirely on that one API staying
available and behaving the same way, and the link id works like a bearer
token: whoever holds it can act as whatever access it grants.

**Recommendation.** Evaluate switching to, or adding, a standard iCal
(`.ics`) subscription feed - the same kind of export calendar.online, Google
Calendar and Outlook can all publish. A proper `.ics` subscription is
read-only by its very nature, which also goes most of the way toward Item 4
below for free, and it would make the next vendor change a config edit
instead of a rewrite of `roster_sync.py`'s calendar.online-specific event
parsing.

## 3. Pair operator names with bus number when scheduling

The schedule's data model already carries both on the same entry -
`ServicePeriod.operator` and `ServicePeriod.vehicles` in
`backend/schedule.py` - but nothing enforces the pairing is correct:

- The admin page's Schedule editor shows `operator` as a free-text field
  (`.sched-operator` in `frontend/js/admin.js`) with no fixed list of known
  drivers to choose from, so the same person can end up spelled three
  different ways across the roster.
- A synced drive's bus is read by matching `"nUWAy <n>"` in the calendar
  event's own title (`VEHICLE_IN_TITLE` in `backend/roster_sync.py`), falling
  back to a configured default vehicle if the title does not name one. A
  typo or an omitted bus number in the calendar event is not an error - it
  silently attributes the drive to the wrong bus, or the fallback bus.

**Recommendation.** Give the Schedule editor a fixed roster of drivers to
pick from instead of free text, and make the calendar-booking convention
name the driver and the bus in a structured way, so a mistake produces a
visible error instead of a silent misattribution.

## 4. Add security to write-protect the calendar

The project's own code already flags this: the same `calendar_online_id`
link used to sync the roster is, under calendar.online's sharing model, also
how someone would open - and potentially edit - the calendar
(`backend/roster_sync.py`'s module docstring). There is no separate
read-only credential for the dashboard's sync versus the link drivers use to
book shifts.

**Recommendation.** Set up a dedicated, read-only share for the dashboard's
sync, distinct from the link used to book shifts, and keep the editable
calendar restricted to known driver accounts rather than one shared link. If
Item 2's iCal subscription is adopted, ask the calendar provider specifically
for a read-only `.ics` URL and keep the editable calendar link separately
and more tightly held.

## 5. Improve GPS startup protocol

A missing GPS fix is already handled gracefully in the data itself
(`gps_status = -1`, a stored "no fix" row rather than a gap or a crash,
`backend/ingest/rev_php.py`), but the onboard unit can still take a while to
get its first fix after power-on - a cold start with no cached almanac is
commonly the slowest case for consumer GPS hardware. During that time the
dashboard shows a bus present with no position, and there is currently no
way to tell "still starting up" apart from "something is wrong."

**Recommendation.** Raise with the shuttle vendor whether the onboard unit
can retain a warm GPS almanac across power cycles, so a restart gets a fix
in seconds rather than minutes, or whether it can publish an explicit
"acquiring fix" status (naturally paired with Item 1's packet extension) so
the dashboard can show that state rather than leaving an operator to guess.

## 6. Make operating hours follow the calendar schedule

The pickup-request operating hours (`pickup_requests.operating_hours` in
`config/app.yaml`, `backend/operating_hours.py`) are a fixed weekly
timetable, kept independently of the actual driving roster
(`utilisation.service_hours`, synced via Items 2 and 4). The two can drift
apart - a public holiday or a cancelled shift takes a bus off the roster,
but the static hours still invite a rider to request a pickup with nobody
rostered to answer it. This was a deliberate, documented trade-off when the
feature shipped (see the note under `GET /api/pickup-requests/hours` in
`docs/api.md`), made so the gate did not have to wait on the roster being
trustworthy enough to drive it.

**Recommendation.** Once the roster is reliable enough to depend on, make
"open" mean "at least one vehicle is currently rostered (and ideally
reporting live)" rather than, or in addition to, the static weekly window -
so a cancelled run or a public holiday closes requests automatically with no
separate config edit needed. `Schedule.covers()` in `backend/schedule.py`
already answers "is anything rostered right now" fleet-wide; this is a matter
of wiring the existing roster into the existing gate, not new mechanics.

## 7. Poor network connectivity of the shuttle buses

Each shuttle is polled over the regular mobile network, and a poll that
fails - a timeout, a dropped connection - is simply skipped until the next
one (`backend/logger.py`). The dashboard already copes with the resulting
gaps (a broken trail past `liveness.inactivity_threshold_seconds`, a bus
flipping to INACTIVE), but a run through patchy coverage still means that
stretch of position history is permanently missing, not just delayed,
because nothing is buffered on the vehicle side to resend later.

**Recommendation.** This is primarily a hardware and connectivity problem -
SIM provider, antenna placement, or a genuine black spot on the route - not
something the dashboard can fix on its own. If the onboard unit supports it,
enabling store-and-forward (buffering unsent positions on the device and
resending them once connectivity returns) would close these gaps instead of
only handling them gracefully. Worth raising with the shuttle vendor
alongside Items 1 and 5, since all three concern the onboard unit's own
firmware and connectivity behaviour rather than this codebase.
