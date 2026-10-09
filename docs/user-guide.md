# User guide

How to use the nUWAy Fleet Dashboard. It has three kinds of user, and each has
its own part of this guide:

| You are | You want to | Read |
|---|---|---|
| A **rider** | Ask a shuttle to collect you. | [Part 1](#part-1-riders) |
| Anyone **watching the fleet** | See where the shuttles are and how well they are used. | [Part 2](#part-2-the-dashboard) |
| An **operator or administrator** | Collect riders, record downtime, and manage the schedule and routes. | [Part 3](#part-3-the-admin-page) |

The dashboard runs in a web browser on a computer, tablet or phone. Nothing
needs installing. Setting it up on a server is covered in the
[installation guide](installation-guide.md).

All dates and times are shown in Perth time.

---

## Part 1: Riders

No account or sign-in is needed.

### Request a pickup

1. Open the dashboard and choose **Rider** at the top.
2. Under **YOUR STOP**, choose the stop you are waiting at. The map shows the
   campus, the stops and where the shuttles are right now.
3. Press **Request pickup**.

The panel changes to **Waiting for the shuttle at** followed by your stop. The
operator can now see that someone is waiting there. Keep the page open; it
checks for updates every few seconds.

Arrival times are not available yet, so the page does not say when the
shuttle will reach you.

### Cancel a request

Press **Cancel request** on the waiting panel.

A request that nobody collects closes by itself after 30 minutes. If you are
still waiting then, request again.

### When you are collected

When the operator marks your stop as picked up, the panel changes to
**You're on board!** You can then:

- press **Leave a review** to tell the team how the ride went, or
- do nothing and carry on; the review is optional.

### Leave a review

The review form has two required questions, each rated 1 (worst) to 5 (best):

- **How safe did you feel?**
- **Requesting a pickup and tracking the bus live**

Everything else is optional: how the vehicle behaved, whether it was on time,
what the ride was for, the stops, the accessibility ramp, a little about you,
and any suggestions. Press **Submit review** to send it, or **Not now** to
skip.

Reviews are anonymous. The form does not ask for your name, and nothing that
identifies you is stored with it. Your answers to "About you" are remembered
on your own device so you are not asked again next time.

---

## Part 2: The dashboard

The dashboard is open to everyone, without signing in. It has three views,
chosen from the tabs at the top:

| Tab | Shows |
|---|---|
| **Fleet** | The map, with each shuttle's position and where it has been. |
| **Rider** | The pickup request panel ([Part 1](#part-1-riders)). |
| **Utilisation** | How the fleet's time was spent over a period. |

Two controls apply to every view: which **vehicles** you are looking at, and
which **period** of time.

### Choosing vehicles

The **VEHICLE** bar under the header has a chip for each shuttle.

- Click a shuttle's chip to show only that one. Click more chips to add more.
- Click a selected chip again to take it out.
- **All vehicles** shows the whole fleet.

You can also click a shuttle's row in the **Vehicles** panel on the Fleet view.

Clicking the word **VEHICLE** (or **ROUTE** or **AREA**) folds that bar away
to leave more room for the map. Click it again to bring it back.

### Choosing a period

The calendar bar in the header sets the period. Click it to open the month
and the time controls.

- **Live.** The dashboard opens in live mode: the period runs up to now, and
  the page refreshes itself every 15 seconds. The **Live** button turns this
  on and off.
- **Days.** Click a start day and an end day on the month, or drag across the
  days you want. Days in the future cannot be chosen.
- **Times.** The **Start** and **End** sliders narrow the period to the
  minute. The End slider is not used while Live is on, because the period
  then ends at the present moment.
- A line of text under the controls states the period in plain words.

If there is nothing recorded for the period you chose, the dashboard says
**No data for this period.**

#### The full calendar

The expand button on the calendar bar opens the full calendar. It shows a
week at a time (or three days), with one lane per shuttle:

- **Scheduled** bands show when that shuttle is rostered to run, with the
  operator's name where one is recorded.
- **Downtime** blocks show when it was recorded as out of service.
- An empty lane means the shuttle is rostered off, not that data is missing.

Clicking a scheduled or downtime block opens that shuttle's figures for that
time on the admin page. You will be asked to sign in first.

### Fleet view

#### The Vehicles panel

One row per shuttle:

| Shown | Meaning |
|---|---|
| **ACTIVE** | The shuttle has reported its position within the last 5 minutes. |
| **INACTIVE** | It has not. The row is greyed out. |
| **Last packet ... ago** / **Last seen ...** | When it last reported. "No telemetry received" means it never has. |
| Green, yellow or red dot | How long ago it was last seen: green is today or the last weekday; red is more than 10 days ago; yellow is in between. Hover over the dot for the wording. |
| Speed, battery, GPS | Its latest readings, shown only while it is active. |

The panel header says how many shuttles are active, and the figures at the
bottom of the panel summarise utilisation for the vehicles and period chosen.

#### The map

- Each shuttle is a **small bus in its own colour**, with its number in a
  badge, at its latest position in the period. Click it for its name and how
  many positions were recorded.
- The **coloured line** is where it travelled during the period. The line
  has a break wherever the shuttle stopped reporting for more than 5
  minutes, so a gap in the line means a gap in the data, not a jump.
- **Stops** are the small circles. Hover over one to see its name; click it
  to see which routes serve it, each with a dot in the route's colour.
- A **ring around a stop** means a shuttle came within about 25 metres of it
  during the period, in that shuttle's colour. A stop two shuttles passed
  has two rings, one per shuttle, always in the same order as the Vehicles
  panel.
- The **ROUTE** bar highlights one route. Each chip has a dot in its route's
  colour. Picking one fills that route's stops with its colour, fades the
  others, and zooms the map to the whole route. **All routes** clears it and
  zooms back to the shuttles.
- Two chips at the top right of the map, beside the 2D / 3D switch, change
  how the map is drawn. Each turns blue while it is on, and both are off by
  default. They are not shown on the Rider tab or in 3D.
  - **Focus routes** fades the shuttles' lines and rings, and draws the
    selected route's planned path over them. The shuttles and stops stay at
    full strength.
  - **Full colour** shows the map's own colours, for finding your way by its
    parks and roads. Off, the map is muted so the routes and shuttles stand
    out.
- The **AREA** bar keeps the map on one place, **UWA Campus** or
  **Eglinton**. Without it, the map zooms to fit every shuttle shown, which
  zooms a long way out when shuttles are in both places.

#### 3D view

The **2D / 3D** switch at the corner of the map changes to a 3D view that
follows one shuttle at a time.

- The arrows either side of the shuttle's name, or the left and right arrow
  keys, move to the next shuttle.
- Drag to look around, and scroll to zoom.
- **Spin** circles the camera slowly around the shuttle.
- **Earth** shows real buildings from Google's 3D imagery. It is only
  available if the installation has been given a Google Maps key.

### Utilisation view

This view answers "how was the fleet's time spent?" for the vehicles and
period chosen, using the GMG time usage model.

- The **tiles** at the top are the headline figures.
- **Pie** shows how the period divides between working, operating delay,
  standby, downtime and not reporting.
- **Time model** shows the same time as nested bars: calendar time, split
  into scheduled and unscheduled, and so on down.
- The **table** at the bottom has a row per shuttle and a total row.
- When downtime was recorded in the period, a note says how much and how it
  was counted.

#### What the time categories mean

| Category | Meaning |
|---|---|
| **Calendar time** | All the time in the period. |
| **Scheduled time** | Time the shuttle was rostered to run. |
| **Unscheduled time** | Time outside the roster. |
| **Downtime** | Rostered, but recorded as not fit to run. |
| **Available time** | Rostered and fit to run: scheduled time minus downtime. |
| **Operating time** | Under the control of a driver or the autonomy system: working plus operating delay. |
| **Working** | Moving. |
| **Operating delay** | Stopped away from the depot, or without a GPS fix. |
| **Standby** | Stopped at the depot. |
| **Not reporting** | No position data, so the time cannot be placed. |

#### What the figures mean

Each is a percentage.

| Figure | Meaning |
|---|---|
| **Asset utilisation** | Operating time as a share of all calendar time. |
| **Effective utilisation** | Working time during the roster, as a share of scheduled time. |
| **Operating efficiency** | Working time as a share of operating time: how much running time is lost to stops. |
| **Physical availability** | Available time as a share of scheduled time. |
| **Mechanical availability** | Operating time against operating time plus downtime. |
| **Uptime** | Time the shuttle was able to run, as a share of calendar time. |
| **Use of availability** | Operating time as a share of available time. |
| **Production effectiveness** | Always unavailable: it needs passenger counts, which the shuttles do not report. |

#### "Unavailable" is not zero

A figure the data cannot support is shown as unavailable, with the reason,
and never as 0%. Common reasons:

- **No scheduled time in the period**, for example a weekend. Figures
  measured against the roster cannot be worked out.
- **No operating time in the period.** The shuttle did not run.
- **Nothing rostered for the vehicle.**

Two things affect the figures and are worth knowing:

- **Only downtime inside a shuttle's rostered hours counts.** A repair done
  while the shuttle was rostered off takes nothing from its availability.
- **Recorded downtime replaces the position data for that time.** If a
  shuttle is recorded as down from 10:00 to 11:00, that hour counts as
  downtime whatever its GPS reported.

---

## Part 3: The admin page

The admin page is for operators and administrators. It holds six tabs:
**Operator view**, **Figures**, **Downtime**, **Schedule**, **Routes** and
**Snapshots**.

### Signing in

1. Choose **Admin** at the top right of the dashboard.
2. Enter the username and password.

There is one account, shared by all operators and administrators; whoever
set up the installation has the details. A sign-in lasts 12 hours. Press
**Sign out** when you finish on a shared device. **Return to Dashboard**
goes back to the public dashboard without signing out.

### Operator view

For the person running a shuttle. It lists the stops on your route and how
many riders are waiting at each.

1. Choose your **VEHICLE** and the **ROUTE** it is running.
2. The stops appear in route order. Each shows how many riders are waiting
   and how long the first of them has waited. The list refreshes every
   10 seconds.
3. When you have collected the riders at a stop, press **Picked up** beside
   it. Their request closes and their page changes to "You're on board!"

Notes:

- **Picked up** stays disabled until a vehicle is chosen, because a rider's
  review is recorded against the vehicle that collected them.
- **No riders waiting on this route** means exactly that.
- Your vehicle and route are kept in the page address, so a bookmarked
  tablet reopens on the same pair.
- The panel under the selectors shows where your vehicle is, live or as last
  recorded.

### Figures

Every utilisation figure for a reporting period, in more detail than the
dashboard's Utilisation view.

1. Set **FROM** and **TO**, to the minute.
2. Choose the **VEHICLES** to include.

**KEY PERFORMANCE INDICATORS** lists each figure with its formula and
definition. **TIME CATEGORIES** lists each category with its duration and its
share of calendar time. A figure that cannot be given says why
([see above](#unavailable-is-not-zero)).

The calendar in the header sets the same period, and clicking a block in the
full calendar fills in both the period and the vehicle.

### Downtime

Record when a shuttle was out of service, so the availability figures are
right.

**To add a record:**

1. Choose the **VEHICLE**.
2. Set the **START** and **END**.
3. Enter a **REASON**, for example "scheduled maintenance".
4. Press **Save record**.

A warning appears if the period overlaps an existing record for the same
shuttle. You can still save; overlapping time is only counted once.

**To change or remove a record,** use **Edit** or **Delete** on its row
under **RECORDED DOWNTIME**.

Reasons are visible only to signed-in users. The public dashboard shows how
long a shuttle was down, never why.

### Schedule

When each shuttle is rostered to run. The utilisation figures use this to
tell scheduled time from unscheduled time, so it should match the real
roster.

- Each day of the week holds one or more **periods**, each with a start and
  end time. A day with no periods is not in service.
- A period can be for specific shuttles or for the whole fleet. Periods for
  different shuttles may overlap; two periods for the same shuttle may not.
- A period must end after it starts. For a run past midnight, enter a period
  on each day.
- Press **Save schedule** to apply your changes, or **Discard changes** to
  go back to what was saved.

Changes take effect straight away.

**Synced drives.** If the installation is connected to the REV driving
calendar, drives booked there appear here automatically and cannot be edited
on this page; change them in the calendar itself. **Sync now** fetches the
latest, and **Show past drives** lists earlier ones. Where a synced drive
would overlap a period entered here for the same shuttle, the one entered
here is used.

### Routes

The stop and route editor. A **stop** is a place riders can wait, shared by
every route that serves it. A **route** is a path through stops in order,
shaped by **guide points** that are not stops.

**Getting around**

- The bar at the top lists every route and stop. Click it to open the list,
  then open a route to edit it, or press **New route**.
- The sidebar lists the open route's points in order.

**Editing a route**

- Click the map to add a point. The toggle at the top right of the map sets
  whether a click adds a **Guide point** or a **Stop**.
- Click an existing grey stop to add it to the route.
- Click the route's line to put a guide point in that stretch.
- Drag any point to move it. Moving a stop moves it on every route.
- Drag a row in the sidebar to reorder the points.
- Double-click a guide point to remove it, or a stop to take it off the route.

**Following the paths**

Each stretch of a route follows the campus footpaths unless you draw it
straight. With **Snap new points** on, a new point jumps onto the nearest
path within 25 metres. Select a point to turn its snapping off, for a place
the map has no path across, such as a lawn. **Show paths** shows or hides the
path network.

**Stops on no route**

With no route open, click the map to add a stop, and double-click a stop to
delete it. A stop that riders are currently waiting at cannot be removed
until they have been collected.

**Saving**

Nothing changes until you press **Save changes**; **Discard** throws your
edits away. Until you save, **Undo** and **Redo** (or Ctrl+Z and Ctrl+R; Cmd
on a Mac) step back and forward through your edits. Saved changes show on
the dashboard and in the rider's stop list straight away.

### Snapshots

Choose which figures the system records in its daily snapshot.

1. Tick the metrics to include. At least one must be ticked.
2. Press **Save selection**.

Daily snapshots themselves are not produced yet, so there is nothing to
download under **PAST SNAPSHOTS**. Your selection is kept for when they are.

---

## Common questions

**The map is empty.**
There is no position data for the vehicles and period chosen. Widen the
period, choose **All vehicles**, or turn **Live** on.

**A shuttle shows INACTIVE but I know it is running.**
The dashboard has not received a position from it for 5 minutes. The shuttle
may be out of mobile coverage or its tracker may be off. If every shuttle is
inactive, tell whoever looks after the installation.

**The shuttle's line on the map stops and starts again somewhere else.**
The shuttle did not report for more than 5 minutes in between. The line is
broken there on purpose.

**A figure says "unavailable".**
The data cannot support it for this period; the reason is shown with it. See
["Unavailable" is not zero](#unavailable-is-not-zero).

**The availability figures look too high.**
Check that downtime has been recorded for the period, and that it falls
inside the shuttle's rostered hours on the Schedule tab.

**I requested a pickup and the page went back to the stop picker.**
Your request was closed: it expired after 30 minutes, or the system was
restarted. Request again.

**I was signed out of the admin page.**
Sign-ins last 12 hours. Sign in again; you return to the page you were on.

**Where do rider reviews go?**
They are stored by the system, but the admin page has no screen for reading
them yet. Whoever looks after the installation can retrieve them.
