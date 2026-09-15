A fire behavior simulator at `/app/firesim.py` must be completed so that `python3 /app/firesim.py <config.json>` reads landscape rasters, queries fuel parameters from a SQLite database, computes surface fire behavior with directional spread, propagates fire across the landscape, and writes output rasters.

**Environment:** `/app/firesim.py` (stub), `/app/fuel_models.csv` (parameter table with units in header), `/app/reference.md` (fire behavior equations and constants), `/app/landscape/` (example ESRI ASCII Grid rasters with `.prj` sidecars).

**Config JSON schema:** `landscape_dir` — directory with `fuel_model.asc`, `slope.asc`, `aspect.asc` and `.prj` CRS sidecars; `fuel_db` — SQLite path (table `fuel_models`: fm_num INTEGER PK, fm_code TEXT, is_dynamic INTEGER, depth_ft REAL, mx_dead_pct REAL, load_1h_tpa REAL, load_10h_tpa REAL, load_100h_tpa REAL, load_herb_tpa REAL, load_woody_tpa REAL, sav_1h REAL, sav_herb REAL, sav_woody REAL); `output_dir`; `moisture` — {m_1h, m_10h, m_100h, m_live_herb, m_live_woody} as fractions; `wind` — {speed_mph, direction_from_deg} (compass degrees wind blows FROM); `ignitions` — [[row,col],...]; `max_time_min`.

**Outputs** (in `output_dir`): `rate_of_spread.tif` (ft/min), `fireline_intensity.tif` (Btu/ft/s), `flame_length.tif` (ft), `heading_direction.tif` (degrees CW from north), `eccentricity.tif` ([0,1)), `arrival_time.tif` (minutes; -9999 for unreached), `summary.json` (`{"burned_area_ft2": reached_cell_count * cellsize²}`). All rasters: single-band Float32 GeoTIFF preserving input geotransform, dimensions, and CRS. Nodata: -9999.

**Acceptance criteria:**

- ROS for fuel models 1–13 under standard conditions (m_1h=0.06, m_10h=0.07, m_100h=0.08, m_live_herb=0.60, m_live_woody=0.90, 5 mph from north, flat) within ±0.15 ft/min of: FM1 103.28, FM2 40.22, FM3 129.56, FM4 89.72, FM5 29.05, FM6 37.23, FM7 32.76, FM8 2.23, FM9 9.65, FM10 10.03, FM11 6.73, FM12 14.63, FM13 17.66.
- Fuel models 91–93, 98, 99 and unrecognized numbers: -9999 in all bands, block propagation.
- Increasing wind or slope increases ROS. Increasing dead moisture decreases ROS; at moisture of extinction, ROS near zero. ROS, FLI, and flame length non-negative for burnable cells.
- FLI and flame length increase with wind. Flame length consistent with FLI per `/app/reference.md` (within 0.05 ft).
- Wind from north → heading ≈180°; from east → heading ≈270°.
- Nonzero effective wind: eccentricity in (0,1); calm flat terrain: eccentricity ≈0.
- Ignition cells: arrival_time=0. Arrival increases with distance. With wind, downwind cells reached before upwind. Without wind on flat, cardinal neighbors within 5%.
- A 3-row non-burnable barrier blocks all propagation beyond it.
- Dynamic models (e.g. GR4/104) produce positive ROS; varying live herb moisture changes their ROS.
- Multiple simultaneous ignitions supported.
- Slope-wind interaction changes ROS relative to wind-only.
- Fuel parameters queried from SQLite database; modifying the DB must change output.
