Environmental monitoring data from a coastal surveillance program is in `/app/data/`. PostgreSQL 16 with PostGIS 3 is installed but the service is not running. Local trust authentication is pre-configured.

Build a geospatial analytical pipeline backed by a PostgreSQL database named `waterquality` (user: `postgres`). All distance and proximity computations must use PostGIS geography-type spatial functions — custom coordinate-math implementations will not be accepted.

## Data

- `water_quality_YYYY.csv` (2019--2022): Beach bacteria-count samples. Schemas and date formats evolved across the monitoring period.
- `weather_daily.fwf`: Fixed-width daily meteorological data (specification in `weather_format.txt`).
- `site_metadata.json`: Monitoring site coordinates, water-body type, and environmental-justice demographics.
- `station_locations.csv`: Weather station coordinates.

## Database Requirements

The `waterquality` database must contain the following objects, persisted and accessible after pipeline completion:

- **Table `sites`** with a PostGIS `geom` column (Point, SRID 4326) and a GiST spatial index.
- **Table `stations`** with a PostGIS `geom` column (Point, SRID 4326) and a GiST spatial index.
- **Table `samples`** -- all valid water-quality records from every year, harmonized to a uniform schema.
- **Table `weather`** -- parsed daily observations; sentinel missing-value codes mapped to SQL NULL.
- **Materialized view `mv_site_monthly_summary`** with columns: `site_id`, `year`, `month`, `sample_count`, `exceedance_count`, `exceedance_rate`, `mean_bacteria`.

## Output: `/app/results.json`

| Key | Type | Description |
|-----|------|-------------|
| `total_valid_samples` | int | Valid samples (positive bacteria count, parseable date) across all years |
| `site_nearest_station` | object | `{site_id: station_id}` -- nearest station per site, via PostGIS geography distance |
| `highest_exceedance_site` | string | Site with highest exceedance rate (threshold: 235 CFU/100 mL) |
| `overall_exceedance_rate` | float (4 dp) | Fraction of valid samples exceeding the threshold |
| `marine_freshwater_ratio` | float (4 dp) | Marine exceedance rate / freshwater exceedance rate |
| `precip_exceedance_correlation` | float (3 dp) | Pearson _r_ between site-month mean 3-day antecedent precipitation index and site-month exceedance rate (site-months with >= 2 valid samples and >= 1 defined API-3 value only) |
| `ej_disparity_ratio` | float (4 dp) | Exceedance rate for sites where EJ population >= 50% / exceedance rate for sites where EJ population < 25% |
| `anomalous_sites` | sorted list | Site IDs with exceedance rate exceeding the cross-site mean + 2 sample standard deviations |
| `stations_within_20km` | object | `{station_id: count}` -- distinct monitoring sites within 20 km of each weather station, computed via PostGIS `ST_DWithin` on geography type |

Bacteria values may contain instrument artifacts (e.g., `>` prefixed values represent above-detection-limit results). Only count samples with valid positive bacteria values. A sample exceeds the standard when its count is strictly greater than 235. The 3-day antecedent precipitation index (API-3) is the mean precipitation at the nearest weather station over the 3 calendar days immediately preceding (not including) the sample date, excluding missing days; undefined when all 3 days are missing. Use sample standard deviation (N-1) for all standard-deviation computations.