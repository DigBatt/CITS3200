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

Dates and times are shown in Perth time. The exceptions are the full calendar
and the Downtime and Reviews tabs of the admin page, which use the time zone
of the device you are using.

---

## Part 1: Riders

No account or sign-in is needed.

### Request a pickup

1. Open the dashboard and choose **Rider** at the top.
2. Under **YOUR STOP**, choose the stop you are waiting at. The map shows the
   campus, the stops and where the shuttles are right now. Once you choose,
   it shows only your stop, with its full name.
3. Press **Request pickup**.

The panel changes to **Waiting for the shuttle at** followed by your stop. The
operator can now see that someone is waiting there. Keep the page open; it
checks for updates every few seconds.

Arrival times are not available yet, so the page does not say when the
shuttle will reach you.

### Outside shuttle hours

Pickups can only be requested during shuttle hours. Outside those hours the
panel says **No pickups right now** in place of the stop list, and tells you
when requests open again, for example "They open again tomorrow at 08:00."

If you are already waiting when the hours end, your request stays open and
the operator can still collect you.

### Cancel a request

Press **Cancel request** on the waiting panel.

A request that nobody collects closes by itself after 30 minutes. If you are
still waiting then, request again.

### When you are collected

When the operator marks your stop as picked up, the panel changes to
**You're on board!** You can then:

- press **Leave a review** to tell the team how the ride went, or
- press **Not today** to skip the review. It is optional.

### Leave a review

The review form has two required questions, each rated 1 (worst) to 5 (best):

- **How safe did you feel?**
- **How easy was the app to use?** (requesting a pickup, tracking the bus)

Everything else is optional: how the shuttle behaved, whether it was on time,
what the ride was for, the stops, the accessibility ramp, a little about you,
and any suggestions. Press **Submit review** to send it, or **Not now** to
skip. Each pickup can be reviewed once.

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

Two controls apply to the Fleet and Utilisation views: which **shuttles** you
are looking at, and which **period** of time. The Rider view always shows
every shuttle, today, up to now.

### Choosing vehicles

The **VEHICLE** bar under the header has a chip for each shuttle.

- Click a shuttle's chip to show only that one. Click more chips to add more.
- Click a selected chip again to take it out.
- **All vehicles** shows the whole fleet.

You can also click a shuttle's row in the **Vehicles** panel on the Fleet view.

Clicking the word **VEHICLE** (or **ROUTE** or **AREA**) folds that bar away
to leave more room for the map. Click it again to bring it back.

### Choosing a period

The calendar bar in the header sets the period. Click the month name to open
the month and the time controls.

- **Live.** The dashboard opens in live mode: the period runs up to now, and
  the page refreshes itself every 15 seconds. The **Live** button turns this
  on and off.
- **Days.** Click a start day and an end day on the month, or drag across the
  days you want. Days in the future cannot be chosen.
- **Times.** The **Start** and **End** sliders narrow the period to the
  minute. The End slider is not used while Live is on, because the period
  then ends at the present moment.
- A line of text above the sliders states the period chosen.

If nothing was recorded in the period you chose, the dashboard says
**No data for this period.**

#### The full calendar

The expand button on the calendar bar opens the full calendar. It shows seven
days or three days at a time, with one lane per shuttle:

- **Scheduled** bands show when that shuttle is rostered to run, with the
  operator's name where one is recorded.
- A bar down the middle of the lane shows when the shuttle was operating.
- **Downtime** blocks show when it was recorded as out of service. They are
  shown only to someone signed in to the admin page.
- An empty lane means the shuttle is rostered off, not that data is missing.

The shuttle chips on the full calendar choose which lanes are shown. It also
has its own **Live** button and period slider.

Clicking a block opens that shuttle's figures for that time on the admin
page. You will be asked to sign in first.

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

The panel header says how many shuttles are active. The three figures at the
bottom of the panel summarise utilisation for the shuttles and period chosen.

#### The map

- Each shuttle is a **small bus in its own colour**, with its number in a
  badge, at its latest position in the period. Click it for its name, the time
  of that position and how many positions were recorded in the period.
- The **coloured line** is where it travelled during the period. The line
  has a break wherever the shuttle stopped reporting for more than 5
  minutes, so a gap in the line means a gap in the data, not a jump.
- **Stops** are the small circles. Hover over one to see its name; click it
  to see which routes serve it, each with a dot in the route's colour.
- A **ring around a stop** means a shuttle came within 25 metres of it during
  the period, in that shuttle's colour. A stop two shuttles passed has two
  rings, one per shuttle, in the same order as the Vehicles panel.
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
  **Eglinton**. With **All areas**, the map zooms to fit every shuttle shown,
  which zooms a long way out when shuttles are in both places.

#### 3D view

The **2D / 3D** switch at the top right of the map changes to a 3D view that
follows one shuttle at a time.

- The arrows either side of the shuttle's name, or the left and right arrow
  keys, move to the next shuttle.
- Drag to look around, and scroll to zoom.
- **Spin** circles the camera slowly around the shuttle.
- **Earth** shows real buildings from Google's 3D imagery. It is only
  available if the installation has been given a Google Maps key.

### Utilisation view

This view shows how the fleet's time was spent, for the shuttles and period
chosen, using the GMG time usage model.

- The **tiles** at the top are the three headline figures: asset
  utilisation, effective utilisation and operating efficiency.
- **Pie** shows how the period divides between working, operating delay,
  standby, downtime and not reporting.
- **Time model** shows the same time as stacked bars: calendar time, the
  categories it divides into, and scheduled against unscheduled time.
- The **table** at the bottom has a row per shuttle and, for more than one
  shuttle, a total row. Click a shuttle's row to show only that shuttle.
- When downtime was recorded in the period, a note says how much and how it
  was counted.

#### What the time categories mean

| Category | Meaning |
|---|---|
| **Calendar time** | All the time in the period. |
| **Scheduled time** | Time the shuttle was rostered to run. |
| **Unscheduled time** | Time outside the schedule. |
| **Downtime** | Rostered, but recorded as not fit to run. |
| **Available time** | Rostered and fit to run: scheduled time minus downtime. |
| **Operating time** | Under the control of a driver or the autonomy system: working plus operating delay. |
| **Working** | Moving. |
| **Operating delay** | Stopped away from the depot, or without a GPS fix. |
| **Standby** | Stopped at the depot. |
| **Productive time** | Working time spent carrying passengers. Always unavailable: the shuttles do not report passenger counts. |
| **Not reporting** | No position data, so the time cannot be placed. |

#### What the figures mean

Each is a percentage. The Utilisation view shows the first three; the admin
page's [Figures](#figures) tab shows them all.

| Figure | Meaning |
|---|---|
| **Asset utilisation** | Operating time as a share of all calendar time. |
| **Effective utilisation** | Working time during scheduled time, as a share of scheduled time. |
| **Operating efficiency** | Working time as a share of operating time: how much running time is lost to stops. |
| **Physical availability** | Available time as a share of scheduled time. |
| **Mechanical availability** | Operating time during scheduled time, against that time plus downtime. |
| **Uptime** | Available time as a share of calendar time. |
| **Use of availability** | Operating time during scheduled time, as a share of available time. |
| **Production effectiveness** | Always unavailable: it needs passenger counts, which the shuttles do not report. |

#### "Unavailable" is not zero

A figure the data cannot support is shown as unavailable, with the reason,
and never as 0%. Common reasons:

- **No scheduled time in the period**, for example a weekend. Figures
  measured against the schedule cannot be worked out.
- **No operating time in the period.** The shuttle did not run.
- **Nothing scheduled for the shuttle.**

Two rules affect the figures:

- **Only downtime inside a shuttle's scheduled hours counts.** A repair done
  while the shuttle was rostered off takes nothing from its availability.
- **Recorded downtime replaces the position data for that time.** If a
  shuttle is recorded as down from 10:00 to 11:00, that hour counts as
  downtime whatever its GPS reported.

---

## Part 3: The admin page

The admin page is for operators and administrators. It has seven tabs:
**Operator view**, **Figures**, **Downtime**, **Schedule**, **Routes**,
**Snapshots** and **Reviews**.

### Signing in

1. Choose **Admin** at the top right of the dashboard.
2. Enter the username and password.

There is one account, shared by all operators and administrators; whoever
set up the installation has the details. A sign-in ends 12 hours after it
was last used. Press **Sign out** when you finish on a shared device.
**Return to Dashboard** goes back to the public dashboard without signing
out.

### Operator view

For the person running a shuttle. It lists the stops on your route and how
many riders are waiting at each.

1. Choose your **VEHICLE** and the **ROUTE** it is running.
2. The stops appear in route order. Each shows how many riders are waiting
   and how long the first of them has waited. The list refreshes every
   10 seconds.
3. When you have collected the riders at a stop, press **Picked up** beside
   it. Their requests close and their pages change to "You're on board!"

Notes:

- **Picked up** stays disabled until a shuttle is chosen, because a rider's
  review is recorded against the shuttle that collected them.
- **Picked up** closes every request at that stop, whichever route the rider
  wanted.
- **No riders waiting on this route** means exactly that.
- Your shuttle and route are kept in the page address, so a bookmarked
  tablet reopens on the same pair.
- The panel under the selectors shows where your shuttle is: **LIVE**, or
  **LAST RECORDED** with its age. **VEHICLE HERE** marks the stop it is at.

### Figures

Every utilisation figure for a reporting period, in more detail than the
dashboard's Utilisation view. The tab opens on today so far.

1. Set **FROM** and **TO**, to the minute.
2. Choose the **VEHICLES** to include.

**KEY PERFORMANCE INDICATORS** lists each figure with its formula and
definition. **TIME CATEGORIES** lists each category with its duration and its
share of calendar time. A figure that cannot be given says why
([see above](#unavailable-is-not-zero)).

The calendar in the header sets the same period, and clicking a block in the
full calendar fills in both the period and the shuttle.

### Downtime

Record when a shuttle was out of service, so the availability figures are
right.

**To add a record:**

1. Choose the **VEHICLE**.
2. Set the **START** and **END**, in the time of the device you are using.
3. Enter a **REASON**, for example "scheduled maintenance".
4. Press **Save record**.

All four fields are required. If the period overlaps an existing record for
the same shuttle, a warning lists the records it overlaps and the button
changes to **Save anyway**. Press it to save, or change the times.
Overlapping time is only counted once.

**To change or remove a record,** use **Edit** or **Delete** on its row
under **RECORDED DOWNTIME**.

Reasons are visible only to signed-in users. The public dashboard shows how
long a shuttle was down, never why.

### Schedule

When each shuttle is rostered to run. The utilisation figures use this to
tell scheduled time from unscheduled time, so it should match the real
roster.

- Each day of the week holds one or more **periods**, each with a start and
  end time. **Add period** adds one. A day with no periods is not in service.
- A period can be for specific shuttles or, with **All**, for the whole
  fleet. Periods for different shuttles may overlap; two periods for the same
  shuttle may not.
- A period must end after it starts. For a run past midnight, enter a period
  on each day.
- **Operator** is optional. The name is shown on the full calendar.
- Tick **Start on** to have a period begin on a later date. **Remove** takes
  a period off now, or from a date you choose.
- Press **Save schedule** to apply your changes, or **Discard changes** to
  go back to what was saved.

Saved changes take effect straight away, and the next daily snapshot uses
them.

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
  then open a route to edit it, or press **New route**. Stops are renamed
  in this list.
- The sidebar shows the open route's name and colour, and lists its points
  in order. Tick **Loop back to the first point** for a circular route.
  **Delete route** removes it.

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
straight: the button on a point's row switches the stretch arriving there
between **Follows paths** and **Drawn straight**. With **Snap new points**
on, a new point jumps onto the nearest path within 25 metres. Select a point
to turn its snapping off, for a place the map has no path across, such as a
lawn. **Show paths** shows or hides the path network.

**Stops on no route**

With no route open, click the map to add a stop, and double-click a stop to
delete it. A stop that riders are waiting at cannot be removed until they
have been collected.

**Saving**

Nothing changes until you press **Save changes**; **Discard** throws your
edits away. Until you save, **Undo** and **Redo** step back and forward
through your edits. From the keyboard, Ctrl+Z undoes and Ctrl+Shift+Z or
Ctrl+Y redoes (Cmd on a Mac). On this tab Ctrl+R also redoes, and does not
reload the page. Saved changes apply straight away; a dashboard or Rider tab
that is already open shows them when the page is reloaded.

### Snapshots

A daily snapshot is a saved copy of the chosen figures for one day, midnight
to midnight, for each shuttle. The system saves one just after each day ends,
so there is a record that does not depend on the dashboard.

**To choose what a snapshot records:**

1. Tick the metrics to include. At least one must be ticked.
2. Press **Save selection**.

Your selection applies from the next snapshot. Snapshots already saved keep
the metrics they were made with.

**To download a snapshot,** find its day under **PAST SNAPSHOTS**, newest
first:

| Shown | Meaning |
|---|---|
| **Available**, with **Download** | A snapshot was saved for that day. **Download** gives you a file named `snapshot-` and the date. |
| **No snapshot** | The system was not running when that day ended, so none was saved. One is not made later. The day's positions are still on the dashboard, and its figures on the Figures tab. |

**Refresh** reloads the list. Yesterday's snapshot appears a minute or so
after midnight.

The file is in JSON, a text format that a spreadsheet or script can read. It
states the day, the period it covers and the metrics chosen, then each
shuttle's figures as fractions, so 0.75 means 75%. A figure the data cannot
support is left empty and its reason is given
([see above](#unavailable-is-not-zero)).

A snapshot is not changed once saved. Downtime recorded for a day afterwards
changes that day's figures on the dashboard, but not its snapshot.

### Reviews

What riders said after being collected ([Part 1](#leave-a-review)), newest
first.

- **SUMMARY** gives the number of reviews, the average ratings and the
  average wait across the reviews shown, and says how many that is when a
  filter is on.
- The filters at the top narrow the list by shuttle, by stop and by date
  (today, the last 7 days or the last 30 days). **Rated 2 or lower only**
  keeps just the poor ratings.
- **Expand all** opens every review in full (**Collapse all** closes them
  again), and **Refresh** fetches any that have arrived since.
- **Previous** and **Next** move between pages when there are more than 10.

Reviews are anonymous; see [Leave a review](#leave-a-review) for what is and
is not stored.

---

## Common questions

**The map is empty.**
There is no position data for the shuttles and period chosen. Widen the
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
inside the shuttle's scheduled hours on the Schedule tab.

**I requested a pickup and the page went back to the stop picker.**
Your request was closed because it expired after 30 minutes. Request again.

**I have been waiting and the operator cannot see my request.**
The system may have been restarted, which clears every request. Your page
still shows the request as waiting. Reload the page and request again.

**The Rider tab says "No pickups right now".**
It is outside shuttle hours. The panel says when requests open again. If the
hours shown are wrong, tell whoever looks after the installation.

**I was signed out of the admin page.**
A sign-in ends 12 hours after it was last used. Sign in again; you return to
the page you were on.

**Where do rider reviews go?**
To the **Reviews** tab of the admin page, where anyone signed in can read
them. See [Reviews](#reviews).

**A day says "No snapshot".**
The system was not running when that day ended. Tell whoever looks after the
installation if it keeps happening. See [Snapshots](#snapshots).
