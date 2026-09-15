An automated pipeline ingested Earth observation rasters from multiple satellite missions and generated STAC (SpatioTemporal Asset Catalog) Item JSON files for each. The pipeline has known bugs — several generated STAC items contain metadata errors of varying severity while others are fully correct.

`/app/rasters/` contains six GeoTIFF files (each stored in its native CRS), and `/app/stac_items/` contains the corresponding STAC Item JSON for each raster. The report schema is at `/app/schema/report_schema.json`.

Build `/app/reconcile.py` — a validation tool that audits every STAC item against the ground truth in its raster file and writes a structured report to `/app/output/reconciliation.json`.

## Validation checks

The tool must detect discrepancies across four categories:

- **`spatial_extent`**: The STAC `bbox` must contain WGS84 coordinates per the STAC specification. Rasters stored in projected CRSs (UTM, polar stereographic, sinusoidal, etc.) require coordinate transformation to WGS84 before comparison. Report when the STAC bbox contains projected-CRS meter values, has inverted coordinate signs, or is computed from the wrong projection zone. Include both the erroneous STAC bbox and the correct file-derived WGS84 bbox in the error.
- **`crs_mismatch`**: The STAC `properties.proj:epsg` must match the raster's actual EPSG authority code. Report the STAC EPSG code and the file's true EPSG code.
- **`temporal_extent`**: If `properties.start_datetime` and `properties.end_datetime` are both present, `start_datetime` must precede `end_datetime`. Report when they are inverted.
- **`band_count`**: The length of `properties.eo:bands` must match the raster's actual band count. Report the STAC band count and the file's true band count.

## Severity classification

- **`critical`**: spatial extent and CRS errors (cause incorrect geospatial queries).
- **`major`**: temporal extent and band count errors (cause incomplete data selection).

## Report format

The output JSON at `/app/output/reconciliation.json` must have three top-level keys:

- **`files_analyzed`**: array of file identifiers (the raster filename without its `.tif` extension, e.g. `"global_sst"`).
- **`errors`**: array of error objects, each containing: `file_id` (filename without extension), `error_type` (one of `spatial_extent`, `crs_mismatch`, `temporal_extent`, `band_count`), `field` (the STAC metadata field), `stac_value` (value from the STAC item), `file_value` (value derived from the raster), `severity` (`critical` or `major`), and `description` (human-readable explanation).
- **`summary`**: object with `total_files` (integer), `total_errors` (integer), `critical_count` (integer), `major_count` (integer).

The report must detect every real error while producing zero false positives on correct items. Items whose bbox, CRS, temporal range, and band count are all consistent must generate no errors.