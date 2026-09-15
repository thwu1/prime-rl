A gravity survey was conducted over a region with suspected subsurface density anomalies. Observed total gravity (the sum of the Earth's normal gravitational field and anomalous contributions from buried density contrasts) is recorded at 36 stations in geographic coordinates on the GRS80 reference ellipsoid. Five rectangular prism source bodies have known geometry but unknown densities.

Process this survey to recover the unknown prism densities, produce a gridded map of the gravity anomaly, and verify the physical consistency of your forward model.

**Input files in `/app/`:**
- `survey.csv` — `station_id, longitude, latitude, height, observed_gravity` (GRS80 geodetic coordinates in decimal degrees, ellipsoidal height in meters, total observed gravity in mGal)
- `prisms.json` — 5 prism geometries `{west, east, south, north, bottom, top}` in the local projected frame (easting/northing/upward, meters)
- `proj_string.txt` — coordinate transformation definition string for converting geographic coordinates to the local projected frame
- `eval_points.json` — 8 evaluation points `[x, y, z]` in the local frame

**Required output files in `/app/`:**
- `projected_coords.json` — JSON array of 36 objects `{"easting": ..., "northing": ...}` with survey station positions transformed to the local projected Cartesian frame using the definition in `proj_string.txt`
- `normal_gravity.json` — JSON array of 36 theoretical normal gravity values (mGal) for the GRS80 ellipsoid (a=6378137 m, f=1/298.257222101, GM=3986005×10⁸ m³/s², ω=7292115×10⁻¹¹ rad/s) at each station's geodetic latitude and ellipsoidal height
- `densities.json` — JSON array of 5 recovered density contrasts (kg/m³) that best explain the gravity disturbance (observed gravity minus normal gravity) given the prism geometries
- `anomaly_grid.nc` — NetCDF grid of gravity disturbance interpolated over the region −3000/3000/−3000/3000 (meters) with spacing 125 m and tension factor 0.25
- `gradient_max.json` — `{"easting": ..., "northing": ..., "magnitude": ...}` location (projected meters) and value (mGal/m) of the maximum horizontal gradient magnitude of the gridded gravity disturbance
- `laplace_check.json` — JSON array of 8 values of g_ee + g_nn + g_uu (1/s²) at the evaluation points, computed from the gravitational potential of all 5 prisms with recovered densities; these verify that the potential satisfies Laplace's equation outside source bodies

Use G = 6.6743e-11 m³/(kg·s²). All prism computations use an easting/northing/upward coordinate system.