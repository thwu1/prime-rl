Given rasters, parameter tables, a rainfall hyetograph, and a simulation configuration in `/app/`, implement a physically-based event rainfall-runoff simulator.

**Entry point:** `python3 /app/run_simulation.py`

**Inputs (in `/app/`):**

- `dem.asc`, `soiltype.asc`, `landcover.asc` — ESRI ASCII Grid rasters (15×15, cellsize 20 m, xllcorner 500000, yllcorner 5600000)
- `soil_params.csv` — maps `type` to `ksat_mm_hr,porosity,initial_moisture,suction_mm,depth_mm`
- `landcover_params.csv` — maps `type` to `manning_n,vegetation_cover,canopy_storage_mm`
- `rainfall.csv` — `time_min,intensity_mm_h`; peak 60 mm/h at t=30 min; ends t=65 min; trapezoidal integral ~33.75 mm
- `simulation.conf` — INI: `timestep_s=30`, `duration_min=120`, `crs=EPSG:32632`, file paths, output dir

**Required outputs in `/app/output/`:**

`totals.csv` — `variable,value` rows: `total_rainfall_mm` (~33.75±1), `total_interception_mm`, `total_infiltration_mm`, `total_outflow_mm`, `peak_discharge_m3s`, `peak_time_min`, `mass_balance_error_pct`, `runoff_coefficient`. All non-negative.

`totalseries.csv` — columns: `time_min,rainfall_mm,interception_mm,infiltration_mm,surface_storage_mm,outflow_mm,mass_balance_error_pct`. Values are cumulative catchment-average mm. Cumulative rainfall/interception/infiltration/outflow monotonically non-decreasing. Surface storage non-negative throughout; final value below 30% of total rainfall.

`hydrograph.csv` — `time_min,discharge_m3s`. ≥200 records. Starts below 0.001 m³/s. Peak between 0.001–2.0 m³/s, occurring at t=30–120 min (lagging peak rainfall). Last 10 records below 50% of peak.

`flowdir.tif` — Int16 GeoTIFF. D8 directions: 1=SW 2=S 3=SE 4=W 5=outlet 6=E 7=NW 8=N 9=NE. Exactly one outlet (5) at the lowest boundary cell. All others downhill. NODATA=-9999.

`flowacc.tif` — Int32 GeoTIFF. Upstream cell count including self (min 1). Outlet=225 (total cells). Each cell = 1 + sum of upstream neighbors draining into it. NODATA=-9999.

`maxdepth.tif` — Float32 GeoTIFF. Peak water depth (m). Non-negative, some positive, max below 1.0 m. Deepest cell in lower two-thirds by row. NODATA=-9999.

`flood_extent.geojson` — FeatureCollection of Polygon/MultiPolygon geometries for cells with depth > 0.001 m. Coordinates in EPSG:4326 (lon -180–180, lat -90–90). Each feature has integer `gridcode`=1. At least one feature.

**All GeoTIFFs:** 15×15 pixels. Geotransform origin = upper-left (xllcorner, yllcorner+nrows×cellsize); pixel sizes (+cellsize, −cellsize). CRS=EPSG:32632. Must pass `gdalinfo`.

**Acceptance criteria:**

- Mass balance `(Rain−Interception−Infiltration−SurfaceStorage−Outflow)/Rain×100`: below 1% final, below 2% throughout (past initial 10 records where rainfall > 0.1 mm). Component residual within 1% of rainfall.
- Runoff coefficient 0.05–0.95. Total outflow > 1.0 mm.
- Interception: positive, below rainfall, ≤ max `canopy_storage_mm` + 0.5 mm.
- Infiltration: positive, below rainfall. Rate generally non-increasing over time.
