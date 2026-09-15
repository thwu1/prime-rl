A Landsat 9 Collection 2 Level-2 surface reflectance scene has been processed by an automated pipeline at `/app/pipeline.py`. Spectral bands, QA_PIXEL data, calibration metadata, and analysis zone boundaries are in `/data/`. The file `/data/metadata.json` documents the DN-to-surface-reflectance conversion parameters (scale factor and offset) and the complete QA_PIXEL bit encoding (bits 0–7 and paired confidence bits 8–15).

Independent field validation identified systematic errors in the pipeline's current outputs (`/app/output/`). The validation findings are in `/app/validation_report.txt`.

Diagnose all defects in the pipeline, determine their root causes, produce corrected outputs in `/app/output/`, and create a quantitative quality assessment evaluating the corrected scene's fitness for downstream analysis.

## Required Outputs in `/app/output/`

### Corrected Raster Products

- `cloud_mask.tif` — Binary uint8 mask (1=clear, 0=contaminated). Must flag all quality-affecting conditions documented in the QA_PIXEL bit index: Fill (bit 0), Dilated Cloud (bit 1), Cirrus (bit 2), Cloud (bit 3), and Cloud Shadow (bit 4). The Water bit (bit 7) does not indicate contamination.
- `ndvi.tif` — NDVI (NIR vs Red) as float32, nodata=−9999.0. Valid values in [−1, 1]; all contaminated pixels set to nodata.
- `mndwi.tif` — MNDWI (Green vs SWIR1) as float32, nodata=−9999.0. Same masking and valid-range requirements as NDVI.
- `land_cover.tif` — Thematic classification as uint8. Classes: 0=NoData/contaminated, 1=Water, 2=Vegetation, 3=Built-up, 4=Bare Soil. Only clear pixels receive a nonzero class.
- `ndvi_wgs84.tif` — NDVI reprojected to EPSG:4326 (geographic coordinates) with nodata=−9999.0 preserved.

### Zonal Statistics

- `zonal_stats.csv` — CSV with header row: `zone_id,zone_name,mean_ndvi,mean_mndwi,clear_pixel_count`. One row per zone defined in `/data/analysis_zones.geojson` (4 zones). The `clear_pixel_count` column must reflect only uncontaminated pixels within each zone, not total zone area.

### Quality Assessment

- `quality_assessment.json` — Structured JSON evaluating the corrected scene. Required top-level keys and schema:

  - `defects` — Array of identified pipeline defects. Each object: `id` (string), `category` (string), `description` (string explaining root cause), `affected_pixel_count` (int, number of pixels impacted by this defect), `severity` (one of `"critical"`, `"major"`, `"minor"`). Must cover at minimum: QA masking gaps, calibration error, zonal statistics error, and missing reprojection.

  - `scene_quality` — Object: `clear_pixel_fraction` (float, fraction of total scene pixels passing the corrected cloud mask), `usability_grade` (letter A–F), `grade_justification` (string explaining the grade).

  - `calibration_validation` — Object cross-referencing corrected pipeline output against field spectrometer data from the validation report. Keys: `nir_field_reference` (float, field-measured NIR SR at the NW vegetation site), `nir_pipeline_corrected` (float, mean corrected NIR SR at that site), `nir_residual_abs` (float, absolute difference), `calibration_status` (`"pass"` if residual < 0.05, `"fail"` otherwise).

  - `zone_quality` — Array of per-zone objects: `zone_id` (int), `clear_fraction` (float, fraction of zone pixels that are clear), `data_usability` (`"high"` if clear_fraction > 0.9, `"medium"` if > 0.6, `"low"` otherwise).