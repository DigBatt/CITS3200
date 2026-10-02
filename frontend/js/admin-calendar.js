// The admin page's calendar: the same month bar, overlay, period control and
// full calendar as the dashboard (js/calendar.js, js/timeline.js), and the
// period it picks is the Figures tab's.
//
// The two are kept in step both ways:
//   calendar -> Figures   picking days, scrubbing the sliders, Live, or the
//                         full calendar's tools sets Figures' From and To;
//   Figures -> calendar   editing From or To, or a block clicked through to
//                         Figures, moves the calendar's selection to match.
// `applying` stops a change made by one side echoing back from the other.
//
// On load the calendar takes Figures' period, today so far or whatever a link
// from the dashboard set, rather than imposing its own default.
//
// Loaded last: needs js/calendar.js, js/timeline.js and js/figures.js.
//
// AUTH (S13): view only, over reads that stay public.

(function () {
  const MINUTE_MS = 60000;

  let applying = true; // until the calendar has taken Figures' period
  let timeline = null;

  const calendar = ServiceCalendar.mount({
    mini: document.getElementById('mini-calendar'),
    head: document.getElementById('mini-calendar-head'),
    panel: document.getElementById('mini-calendar-panel'),
    overlay: document.getElementById('cal-overlay'),
    body: document.getElementById('cal-overlay-body'),
    close: document.getElementById('cal-overlay-close'),
  }, {
    // The month bar sits in the header and opens the month and the period
    // control as an overlay, as on the dashboard.
    collapsed: true,
    // The same range adapter as js/main.js, over this page's timeline.
    range: {
      get: () => timeline?.getDates(),
      select: (start, end) => timeline?.setDates(start, end),
      max: () => Timeline.getPerthDateString(),
      window: () => timeline?.getWindow(),
      scrub: (ends) => timeline?.scrub(ends),
      release: () => timeline?.release(),
      setLive: (on) => timeline?.setLive(on),
    },
    // A scheduled or downtime block opens that vehicle's figures for its time.
    onBlock: ({ vehicle, from, to }) => {
      calendar.close();
      Figures.show({ vehicles: [vehicle], from, to });
    },
  });

  timeline = Timeline.createTimelineControl(document.getElementById('timeline-container'), {
    onChange: (range) => {
      calendar.paintRange();
      if (!applying) Figures.setPeriod({ from: range.from, to: range.to });
    },
  });

  // Move the calendar to a period given as UTC instants: its days first,
  // then the times on them, then Live if it runs to now. Each step fires the
  // timeline's onChange, which `applying` keeps from going back to Figures.
  function follow({ from, to }) {
    const startMs = Date.parse(from);
    const endMs = Date.parse(to);
    if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs <= startMs) return;
    const live = endMs >= Date.now() - MINUTE_MS;

    applying = true;
    try {
      timeline.setDates(Timeline.getPerthDateString(new Date(startMs)), Timeline.getPerthDateString(new Date(endMs)));
      if (live) {
        timeline.setLive(true);
        timeline.scrub({ startMs });
      } else {
        if (timeline.getWindow().live) timeline.setLive(false);
        // Figures' To minute is the timeline's end minute, so the two read the
        // same (5:00 pm in both) and a round trip does not drift.
        timeline.scrub({ startMs, endMs });
      }
      timeline.release(); // settle now, rather than on the throttle
    } finally {
      applying = false;
    }
  }

  Figures.onPeriodChange(follow);
  const initial = Figures.getPeriod();
  if (initial) follow(initial);
  applying = false;

  window.AdminCalendar = {
    refresh: () => calendar.refresh(),
    close: () => calendar.close(),
  };
})();
