A Java application at `/app/` implements a geodetic datum transformation engine modeled after NOAA's NADCON5 system. It reads binary grid-shift files, interpolates coordinate shifts at query points, and chains single-step transformations through an ordered datum sequence to convert coordinates between reference frames. The application compiles but produces incorrect results across its processing pipeline. Identify and fix all bugs so the engine passes automated verification.

**Usage:**
```
bash /app/compile.sh
java -cp /app/build gov.noaa.ngs.transform.TransformEngine <lat> <lon> <srcDatum> <destDatum>
```

**Output:** `destLat,destLon,sigLat,sigLon` — comma-separated decimal degrees (negative-West longitude) and uncertainty estimates in arcseconds.

**Binary grid file format (big-endian):**
Header (40 bytes): `latMin` (double, 8B), `lonMin` (double, 8B), `deltaLat` (double, 8B), `deltaLon` (double, 8B), `nRows` (int32, 4B), `nCols` (int32, 4B). Data: `nRows × nCols` IEEE 754 single-precision floats (4B each), row-major starting from the southernmost row at `(latMin, lonMin)`. Null sentinel: −88.8888.

Grid-shift values represent coordinate adjustments in arcseconds. Uncertainty estimates accumulate across chain steps as root-sum-of-squares. Backward transformations (newer to older datums) subtract the interpolated shifts. The datum sequence in the configuration establishes the chronological ordering for chaining transforms across epoch transitions.

**Layout:**
- Source: `/app/src/gov/noaa/ngs/transform/`
- Config: `/app/config/regions.properties`
- Grids: `/app/data/grids/` (populated at test time)
