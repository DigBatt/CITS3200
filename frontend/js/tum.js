// The GMG time usage model's figures, shared by the dashboard's Utilisation
// view and the admin Figures tab: what each figure is, how it is worked out,
// how a selection of vehicles pools into one fleet figure, and whether a
// figure can be shown at all.
//
// Formulas are from docs/GMG Time Utilisation Model.md. Which figures the
// telemetry supports is decided by the backend (backend/metrics/tum.py), which
// returns each one it cannot work out as null with a reason in `unavailable`.
// A figure without a value is shown as unavailable with that reason, never as
// zero (#71).

(function () {
  // Headline KPIs, in the order the Figures tab lists them: the three the
  // telemetry supports first, then the five that need data it does not have.
  const KPIS = [
    {
      key: 'asset_utilisation',
      name: 'Asset utilisation',
      formula: 'OT / CT',
      definition: 'Operating time as a proportion of all calendar time.',
    },
    {
      key: 'effective_utilisation',
      name: 'Effective utilisation',
      formula: 'WT in ST / ST',
      definition: 'Working time during scheduled service hours as a proportion of scheduled time.',
    },
    {
      key: 'operating_efficiency',
      name: 'Operating efficiency',
      formula: 'WT / OT',
      definition: 'Working time as a proportion of operating time: how much running time is lost to stops.',
    },
    {
      key: 'physical_availability',
      name: 'Physical availability',
      formula: 'AT / ST',
      definition: 'Available time as a proportion of scheduled time.',
    },
    {
      key: 'mechanical_availability',
      name: 'Mechanical availability',
      formula: 'OT / (OT + DT)',
      definition: 'Operating time against operating time plus downtime: the cleanest read on maintenance impact.',
    },
    {
      key: 'uptime',
      name: 'Uptime',
      formula: 'AT / CT',
      definition: 'Time the fleet was able to run, scheduled or not, as a proportion of calendar time.',
    },
    {
      key: 'use_of_availability',
      name: 'Use of availability',
      formula: 'OT / AT',
      definition: 'Operating time as a proportion of available time: how well the operation uses the fleet it has in working order.',
    },
    {
      key: 'production_effectiveness',
      name: 'Production effectiveness',
      formula: 'PT / OT',
      definition: 'Productive time as a proportion of operating time.',
    },
  ];

  // Time categories, top of the model down. `depth` is how far each nests
  // under calendar time, for indenting. Not reporting is not a GMG category:
  // it is the time the telemetry cannot place at all.
  const TIME = [
    { key: 'calendar_seconds', code: 'CT', depth: 0, name: 'Calendar time', definition: 'All the time in the reporting period.' },
    { key: 'scheduled_seconds', code: 'ST', depth: 1, name: 'Scheduled time', definition: 'Service hours: time the fleet is rostered to run.' },
    { key: 'unscheduled_seconds', code: 'UT', depth: 1, name: 'Unscheduled time', definition: 'Outside service hours.' },
    { key: 'available_seconds', code: 'AT', depth: 2, name: 'Available time', definition: 'Scheduled and fit to run. AT = ST − DT.' },
    { key: 'downtime_seconds', code: 'DT', depth: 2, name: 'Downtime', definition: 'Wanted, but not in a condition to run.' },
    { key: 'operating_seconds', code: 'OT', depth: 3, name: 'Operating time', definition: 'Under the control of a driver or the autonomy system.' },
    { key: 'standby_seconds', code: 'SB', depth: 3, name: 'Standby', definition: 'Fit to run but not operating: stopped at the depot.' },
    { key: 'working_seconds', code: 'WT', depth: 4, name: 'Working time', definition: 'Moving and reporting.' },
    { key: 'operating_delay_seconds', code: 'OD', depth: 4, name: 'Operating delay', definition: 'Stopped away from the depot, or without a GPS fix.' },
    { key: 'productive_seconds', code: 'PT', depth: 5, name: 'Productive time', definition: 'Working time that directly carries passengers.' },
    { key: 'not_reporting_seconds', code: 'NR', depth: 1, name: 'Not reporting', definition: 'No telemetry: time the model cannot place.' },
  ];

  // For a figure left null without a reason. The backend gives one for every
  // case it knows of (tests/test_metrics_unavailable.py); this is the backstop
  // so a figure is never shown blank.
  const FALLBACK_REASON = 'not enough data in this period to work this out';

  const ratio = (part, whole) => (part != null && whole ? part / whole : null);
  const keysOf = (entries, field) => [...new Set(entries.flatMap((entry) => Object.keys(entry[field] ?? {})))];

  /**
   * One vehicle's figures, or a selection's pooled into one: times summed as
   * vehicle-hours, and the three supported KPIs worked out again from those
   * sums rather than averaged. A reason holds for the pool only if it holds
   * for every vehicle; otherwise the pooled figure stands on the vehicles
   * that do have it. Notes are pooled the same way.
   */
  function pool(entries) {
    if (entries.length === 1) return entries[0];

    const buckets = {};
    for (const key of keysOf(entries, 'buckets')) {
      buckets[key] = entries.every((entry) => entry.buckets[key] != null)
        ? entries.reduce((total, entry) => total + entry.buckets[key], 0)
        : null;
    }

    const kpis = {};
    for (const key of keysOf(entries, 'kpis')) kpis[key] = null;
    Object.assign(kpis, {
      asset_utilisation: ratio(buckets.operating_seconds, buckets.calendar_seconds),
      effective_utilisation: ratio(buckets.scheduled_working_seconds, buckets.scheduled_seconds),
      operating_efficiency: ratio(buckets.working_seconds, buckets.operating_seconds),
    });

    const unavailable = {};
    for (const key of keysOf(entries, 'unavailable')) {
      if (entries.every((entry) => entry.unavailable[key])) unavailable[key] = entries[0].unavailable[key];
    }

    // Notes (e.g. "no service schedule is in the system") follow the same
    // rule: they hold for the pool only if they hold for every vehicle.
    const notes = {};
    for (const key of keysOf(entries, 'notes')) {
      if (entries.every((entry) => entry.notes?.[key])) notes[key] = entries[0].notes[key];
    }

    return { buckets, kpis, unavailable, notes };
  }

  /**
   * A figure as it should be shown: `{ value }` when it can be, or
   * `{ reason }` when the data cannot support it. A reason wins over a value,
   * since the backend can give a number it knows is not meaningful (standby
   * with no depot configured is 0, but not a real 0).
   *
   * @param {{buckets: Object, kpis: Object, unavailable: Object}} figures
   * @param {'buckets'|'kpis'} group
   * @param {string} key
   */
  function read(figures, group, key) {
    const value = figures[group]?.[key];
    const reason = figures.unavailable?.[key] || (value == null ? FALLBACK_REASON : null);
    return reason ? { value: null, reason } : { value, reason: null };
  }

  // "needs downtime; ..." reads as a sentence once it has a capital.
  const sentence = (text) => (text ? text.charAt(0).toUpperCase() + text.slice(1) + (text.endsWith('.') ? '' : '.') : '');

  window.TUM = { KPIS, TIME, pool, read, ratio, sentence };
})();
