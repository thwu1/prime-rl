A GeoPackage at `/app/site_data.gpkg` contains four vector layers (`boundary`, `hospitals`, `roads`, `flood_zones`) in EPSG:32636 (UTM Zone 36N) for an urban site suitability analysis. A configuration file at `/app/criteria.json` specifies weighted criteria with scoring rules, analysis grid parameters, candidate identification requirements, and all output format specifications.

Produce:

1. **`/app/output/suitability.tif`** — A single-band GeoTIFF in EPSG:32636 covering the `boundary` layer's extent at the configured resolution. Each pixel encodes a suitability score (10–100) reflecting how well that location satisfies all criteria per the formula and weights in the configuration.

2. **`/app/output/candidates.json`** — A JSON array of candidate site objects. Each represents a contiguous patch of pixels (using the connectivity specified in the configuration) scoring strictly above the configured suitability threshold and meeting the minimum contiguous area requirement. Patches are sorted by `mean_suitability` descending with fields as defined in `criteria.json`.

3. **`/app/output/results.json`** — Summary statistics derived from the suitability raster and candidate analysis, with every field listed under `output.results_format` in `criteria.json`.