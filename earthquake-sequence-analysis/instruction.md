A USGS FDSN earthquake catalog covering global M4+ events from January 1-2, 2024 is at `/app/data/catalog.json` (GeoJSON FeatureCollection; coordinates are `[longitude, latitude, depth_km]`). A machine-readable output specification is at `/app/output_spec.json`.

Produce a comprehensive seismological characterization of the 2024 Noto Peninsula, Japan earthquake sequence. Implement your analysis as `/app/pipeline.py`, writing results to `/app/analysis.json` and a normalized SQLite database to `/app/noto_seismic.db`.

## Spatial Filter

Filter to the Noto Peninsula region: latitude [36.5, 38.5], longitude [136.0, 138.5].

## Database (`/app/noto_seismic.db`)

Create two tables:

**`events`** (one row per filtered event): `id` TEXT PK, `time_ms` INTEGER, `latitude` REAL, `longitude` REAL, `depth_km` REAL, `magnitude` REAL, `mag_type` TEXT, `place` TEXT, `gap` REAL, `dmin` REAL, `rms` REAL, `sig` INTEGER, `status` TEXT, `tsunami` INTEGER.

**`interevent_distances`** (consecutive time-ordered event pairs): `event1_id` TEXT, `event2_id` TEXT, `distance_km` REAL, `time_diff_sec` REAL. Distances use Haversine great-circle formula with Earth radius 6371.0 km. Time differences in seconds.

## Analysis (`/app/analysis.json`)

Write a JSON object with these fields:

| Field | Type | Method |
|---|---|---|
| `event_count` | int | Total filtered events |
| `mainshock` | object | Highest-magnitude event. Keys: `id`, `magnitude`, `latitude`, `longitude`, `depth_km`, `time_ms` |
| `largest_aftershock` | object | Highest-magnitude event occurring after the mainshock (same keys as mainshock) |
| `bath_law_delta` | float | Mainshock magnitude minus largest aftershock magnitude |
| `foreshock_count` | int | Number of filtered events occurring before the mainshock origin time |
| `mc` | float | Completeness magnitude via Maximum Curvature (mode of the non-cumulative frequency-magnitude distribution, bin width 0.1) |
| `b_value` | float | Gutenberg-Richter b-value via Aki-Utsu maximum likelihood estimation for events with magnitude >= Mc |
| `b_value_uncertainty` | float | b-value uncertainty via Shi & Bolt (1982) |
| `a_value` | float | log10(N) where N = count of events with magnitude >= Mc |
| `omori` | object | Modified Omori Law parameters fitted to aftershock rate decay in 1-hour bins: n(t) = K*(t+c)^(-p). Keys: `K`, `c`, `p`. Physical constraints: 0.3 < p < 3.0, c > 0, K > 0 |
| `aftershock_zone_length_km` | float | Maximum pairwise Haversine distance among all aftershock epicenters (rupture zone proxy) |
| `total_energy_joules` | float | Summed seismic energy for all filtered events via the Gutenberg-Richter energy-magnitude relation |
| `mainshock_energy_fraction` | float | Ratio of mainshock energy to total sequence energy |
| `median_interevent_distance_km` | float | Median Haversine distance between consecutive time-ordered event pairs |
| `mean_interevent_distance_km` | float | Arithmetic mean of the same |
| `spatial_density` | object | Densest 0.5-degree floor-aligned grid cell. Keys: `grid_cell_lat_min`, `grid_cell_lon_min`, `count` |

Results must be scientifically accurate and consistent with standard observational seismology methodology.