## Data

- `/app/data/embeddings.tif` — 100×100 multi-band GeoTIFF (EPSG:4326, 16 bands) containing per-pixel embedding vectors from a satellite foundation model. Some pixels are cloud-masked (NaN across all bands).
- `/app/data/labels_sample.tif` — Sparse ground-truth land cover labels for a subset of valid pixels (0 = unlabeled, 1–5 = land cover classes).
- `/app/data/metadata.json` — Class definitions and spatial reference information.
- `/app/data/report_schema.json` — Required JSON structure for the analysis report, specifying all field names, types, and expected semantics.

## Task

Implement `/app/analyze.py` that, when executed via `python3 /app/analyze.py`, writes three output files to `/app/output/`. NaN-embedding pixels must be excluded from all analyses.

### `classified_map.tif`

Single-band uint8 GeoTIFF (100×100). Every valid pixel assigned a land cover class (1–5); NaN-embedding pixels value 0. CRS and affine transform must exactly match `embeddings.tif`. Must contain all 5 land cover classes. Spatial accuracy against the true land cover distribution must exceed 80%.

### `confidence_map.tif`

Single-band float32 GeoTIFF (100×100) with per-pixel classification confidence in [0.0, 1.0]. NaN-embedding pixels must have confidence 0.0. CRS and transform must match the input. Mean confidence across valid pixels must exceed 0.3. Spatial standard deviation must exceed 0.01.

### `report.json`

Quantitative analysis report conforming exactly to `/app/data/report_schema.json`. Every field defined in the schema is required with correct types. Classification accuracy on labeled pixels must exceed 0.85. Every per-class F1 score must exceed 0.70. Confusion matrix must be at least 5×5.