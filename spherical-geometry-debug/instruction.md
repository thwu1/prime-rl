The TypeScript project at `/app/` implements a spherical geometry library for GeoJSON objects. The source files in `/app/src/` contain mathematical bugs and incomplete implementations. Fix all issues so the library produces correct results for all exported functions.

Build with `cd /app && npm install && npx tsc`. The compiled module at `/app/dist/index.js` must export:

**`sphericalArea(geojson): number`** — Spherical excess area in steradians on the unit sphere. A `{type: "Sphere"}` has area 4π. A polygon `[[0,0],[0,90],[90,0],[0,0]]` (semilune) has area π/2. Both clockwise and counter-clockwise polygon windings must yield correct positive area.

**`sphericalCentroid(geojson): [number, number]`** — Returns `[longitude, latitude]` in degrees. For mixed geometry types, the highest-dimensional geometry dominates: polygon surface centroid takes priority over line arc-length centroid, which takes priority over point arithmetic mean. Returns `[NaN, NaN]` for ambiguous cases (e.g., the whole sphere, antipodal points).

**`sphericalContains(geojson, point): boolean`** — Returns `true` if the GeoJSON geometry contains the `[lon, lat]` point (degrees). Must handle polygons with holes, polygons enclosing the poles, and antimeridian crossings. A `{type: "Sphere"}` contains every point.

**`sphericalDistance(a, b): number`** — Great-circle distance in radians between two `[lon, lat]` points (degrees). Must use the proper spherical formula, not Euclidean approximation.

**`sphericalInterpolate(a, b): InterpolateResult`** — Returns a callable `(t: number) => [lon, lat]` with a `distance: number` property giving great-circle distance in radians. At `t=0` returns `a`, at `t=1` returns `b`. Intermediate values must follow the great-circle arc, not a linear path in degree space.

Tolerances: areas within 1e-5, coordinates and distances within 1e-6. The GeoJSON streaming infrastructure (`stream.ts`, `types.ts`, `math.ts`, `cartesian.ts`, `adder.ts`) is correct and does not need modification.
