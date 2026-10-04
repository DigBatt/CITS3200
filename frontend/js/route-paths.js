// Planned paths traced from the route sketches. These are not GPS trails.
// Stop vertices always come from /api/stops, so paths meet marker centres.
(function () {
  function pathsFor(route, stops) {
    if (!route) return [];
    const byId = new Map(stops.map(stop => [stop.id, [stop.latitude, stop.longitude]]));
    const required = ['reid-library', 'ezone-central', 'civ-mech', 'guild-village',
      'law-library', 'barry-marshall', 'sports-science', 'business-school',
      'bilya-marlee', 'marine-research'];
    // Other installations may use a different stop network.
    if (!required.every(id => byId.has(id))) return [];
    const [reid, ezone, civil, guild, law, barry, sports, business, bilya, marine] =
      required.map(id => byId.get(id));

    // Cubic curves only where the sketches follow a curved path. Straight
    // sections and square corners are explicit vertices, never auto-smoothed.
    function curve(a, b, c, d) {
      const points = [a];
      for (let i = 1; i < 16; i++) {
        const t = i / 16, u = 1 - t;
        points.push([0, 1].map(k => u*u*u*a[k] + 3*u*u*t*b[k] + 3*u*t*t*c[k] + t*t*t*d[k]));
      }
      points.push(d);
      return points;
    }
    function join(...parts) {
      return parts.flat().filter((p, i, all) => !i || p[0] !== all[i-1][0] || p[1] !== all[i-1][1]);
    }
    const reverse = path => [...path].reverse();
    const reidSouth = [-31.97925, reid[1]];
    const northwest = [reidSouth[0], 115.81733];
    const west = join([reid, reidSouth, northwest],
      curve(northwest, [-31.97952, northwest[1]], [-31.97951, ezone[1]], ezone), [civil]);
    const east = join([reid, reidSouth],
      curve(reidSouth, [-31.97943, reidSouth[1]], [-31.97954, guild[1]], [-31.97978, guild[1]]),
      [guild]);
    // Keep the shared oval arc above the car park; stop endpoints stay fixed.
    const bottom = curve(civil, [-31.98103, civil[1]], [-31.98113, guild[1]], guild);
    const libraryJunction = [reidSouth[0], guild[1]];
    const lawSpur = [reidSouth, libraryJunction, [reidSouth[0], law[1]], law];
    // Engineering's sketch uses the straight path south of the oval.
    const engineering = [civil, [-31.98102, civil[1]], [-31.98102, guild[1]], guild];
    const marineSpur = [civil, [marine[0], civil[1]], marine];

    // Junction on the straight Saw Promenade segment, with no lateral kink.
    const junctionLat = -31.98232;
    const fraction = (junctionLat - guild[0]) / (barry[0] - guild[0]);
    const junction = [junctionLat, guild[1] + fraction * (barry[1] - guild[1])];
    const south = [guild, junction, barry, sports];
    const bend = [junctionLat, 115.81936];
    const crossCampus = join([junction, bend],
      curve(bend, [-31.98255, 115.81950], [-31.98268, bilya[1]], [-31.98270, bilya[1]]), [bilya]);
    // The uploaded config puts Business School at the Underwood car park,
    // north of the marker in the sketch. Use that real configured stop.
    const underwood = [bilya, [business[0], bilya[1]], business];
    const southCrossing = [sports, [sports[0], business[1]], business];

    // Branches are separate polylines: never close them with a diagonal.
    switch (route.id) {
      case 'full-campus-loop':
        return [west, east, bottom, lawSpur, marineSpur, south, crossCampus, underwood, southCrossing];
      case 'eng-business-loop':
        return [engineering, south, crossCampus, underwood, southCrossing];
      case 'nth-south':
        return [join(east, south)];
      case 'james-oval-loop':
        return [join(west, bottom, reverse(east)), lawSpur];
      case 'library-service':
        return [[reid, reidSouth], lawSpur,
          [libraryJunction, guild, barry]];
      default:
        return [];
    }
  }
  window.RoutePaths = { pathsFor };
})();
