Thirteen geospatial dataset metadata files at `/app/datasets/` describe Earth observation and derived products using varied formats, schemas, and coordinate reference systems. Some files contain metadata anomalies that must be detected and corrected to produce accurate results.

Build `/app/reconciler.py` so that running:

```
python3 /app/reconciler.py /app/datasets/ /app/config.json /app/output/report.json
```

produces a JSON reconciliation report at `/app/output/report.json`. The configuration at `/app/config.json` defines the target area of interest, a thematic taxonomy, and duplicate detection parameters.

The report must contain these top-level keys:

- `datasets`: Array of all 13 normalized dataset records. Each must have `name`, `bbox` (WGS84 `[west, south, east, north]`), `temporal_start` (ISO date string), `temporal_end` (ISO date string), `resolution_m`, `original_crs`, and `theme` (mapped to the config taxonomy).
- `spatial_overlaps`: Pairwise spatial overlap records (`dataset_a`, `dataset_b`, `intersection_area_sq_deg`, `iou`) for all pairs with non-zero WGS84 bounding box intersection.
- `temporal_overlaps`: Pairwise temporal overlap records (`dataset_a`, `dataset_b`, `overlap_days`) for all pairs with positive temporal intersection.
- `aoi_coverage`: Object mapping each dataset name to its percentage (0-100) of AOI coverage.
- `duplicate_candidates`: Array of two-element arrays identifying dataset pairs that likely represent the same underlying source.
- `stac_items`: Array of STAC v1.0.0 compliant Item objects for each unique dataset.
- `data_quality`: Array of detected metadata anomalies. Each entry must have `dataset`, `issue_type`, and `description` fields.