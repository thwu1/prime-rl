Environmental monitoring station data across Central Europe is provided in `/app/data/` in mixed coordinate reference systems and formats. A metadata file at `/app/data/metadata.json` documents the CRS and format of each dataset. Two of the GeoJSON files store coordinates in projected CRS (not WGS84) — the metadata specifies which.

Set up PostgreSQL with PostGIS, load all datasets into a spatial database with correct CRS handling, and produce the following analysis results in `/app/results/`:

## Required Outputs

**`analysis_1.csv`** — Per-district statistics. Columns: `district_id`, `num_stations`, `avg_pollutant`, `max_pollutant`, `area_km2`. Spatially join stations to the district that contains them. Compute district areas in EPSG:3035 (meters). Round `avg_pollutant`, `max_pollutant`, and `area_km2` to 2 decimal places. Districts with no stations should show 0 for all numeric columns. Sort by `district_id`.

**`analysis_2.csv`** — DBSCAN spatial clustering of all stations using projected coordinates in EPSG:3035. Parameters: `eps=15000` meters, `minpoints=3`. Columns: `station_id`, `cluster_id`, `cluster_size`. Noise points get `cluster_id = -1` and `cluster_size = 0`. Sort by `station_id`.

**`analysis_3.csv`** — River analysis per district. Columns: `district_id`, `river_length_km`, `station_river_proximity_avg_m`. Clip rivers to each district boundary and compute total clipped length. For each station within a district, compute its minimum distance to any river. Report the average of those minimum distances per district. All length/distance computations in EPSG:3035. Round to 2 decimal places. Districts with no rivers or stations show 0. Sort by `district_id`.

**`analysis_4.csv`** — Stations located inside protected areas. Columns: `station_id`, `protected_area_id`, `pollutant_reading`, `is_above_threshold` (1 if `pollutant_reading > 75`, else 0). Sort by `station_id`, then `protected_area_id`.

**`summary.json`** — JSON object with keys:
- `total_stations_in_protected_areas` (int): count of distinct stations inside any protected area
- `district_with_highest_avg_pollutant` (string): district_id of the district with the highest average pollutant reading
- `total_river_length_km` (float): total length of all rivers computed in EPSG:3035, rounded to 2 decimals
- `num_clusters` (int): number of DBSCAN clusters (excluding noise)
- `largest_cluster_size` (int): size of the largest cluster