Implement `/app/dambreak_analysis.py` that computes the analytical flow field for a granular column release on an inclined plane and produces multi-format geospatial outputs with structured result storage.

**Physical scenario**: A uniform rectangular column of granular material at rest occupies `columnXMinM` ≤ x ≤ `columnXMaxM` on an inclined plane. At t=0 the downslope face is instantaneously released. Flow is governed by depth-averaged mass and momentum conservation with Coulomb basal friction and an earth pressure coefficient relating lateral stress to overburden. The slope angle exceeds the friction angle. Coordinates: x along slope (downhill positive), y cross-slope (uniform, 1-D problem).

**Input**: `/app/dambreak.ini` — INI configuration with `[DAMBREAK]`, `[GENERAL]`, `[OUTPUT]` sections. List values use `|` as delimiter (e.g. `timeStepsS = 5.0|10.0|15.0|20.0`).

**Outputs** (all under `/app/output/`):

1. **ESRI ASCII rasters**: For each resolution `r` and time step `t`:
   `/app/output/{r}m/pft_t{t}s.asc` (flow thickness), `/app/output/{r}m/pfv_t{t}s.asc` (velocity magnitude). Integer formatting for whole values (`5m`, `10s`). Standard 6-line header: `ncols`, `nrows`, `xllcorner`, `yllcorner`, `cellsize`, `NODATA_value -9999`. Evaluate at cell centers. Zero in no-flow cells.

2. **GeoTIFF rasters**: Corresponding `.tif` at same path stems (`pft_t{t}s.tif`, `pfv_t{t}s.tif`), produced using GDAL. Must be readable by `gdalinfo` with dimensions matching the ASC counterpart.

3. **SQLite database** `/app/output/results.db`:
   - Table `convergence(coarse_m REAL, fine_m REAL, time_s REAL, l2_pft REAL, lmax_pft REAL)` — one row per consecutive resolution pair (resolutions sorted descending) per time step. `l2_pft` = RMS of thickness difference; coarse field linearly interpolated onto fine grid along x.
   - Table `energy_line(key TEXT PRIMARY KEY, value REAL)` — keys: `runout_angle_deg`, `theoretical_alpha_deg`, `mass_center_x_m`, `mass_center_z_m`, `kinetic_altitude_m`. Computed at finest resolution and last time step using mass-weighted averaging over the flow field. `theoretical_alpha_deg` is the expected energy-line angle for pure Coulomb friction on steepest descent.

**Constraints**:
- The tool must exit with return code 0 on success.
- Discrete mass integral matches initial mass within 2% relative error at all resolutions and time steps.
- Runout angle within 2° of friction angle.
- L2 thickness error decreases with resolution refinement at each time step.
- All GeoTIFF files readable by `gdalinfo` with correct dimensions.
- Must be idempotent: repeated runs produce correct output regardless of prior state.

Run: `python3 /app/dambreak_analysis.py`
