A Landsat 8 scene over a mixed land-cover area (forest, urban, agriculture, water) has been processed to estimate Land Surface Temperature. The raw input data is in `/app/data/` and the analyst's processed outputs are in `/app/data/flawed/` along with their processing notes.

Quality reviewers flagged several issues: certain LST values appear physically implausible, quality masking seems insufficient for reliable analysis, and the relationship between surface properties and temperature may not be adequately captured.

Assess the flawed analysis against the raw data and scene metadata. Identify the processing errors, then produce scientifically corrected results.

## Available Data

**Raw inputs** (`/app/data/`): Landsat 8 OLI/TIRS bands (Red and NIR surface reflectance, Band 10 thermal Level-1 DN), QA_PIXEL quality band (Collection 2 Level-1 bit-packed encoding), radiometric metadata JSON, and polygon zone definitions in GeoJSON. All rasters are 200x200 pixels at 30 m resolution in EPSG:32618.

**Previous analysis** (`/app/data/flawed/`): Processed GeoTIFFs (valid_mask, NDVI, emissivity, LST), zonal statistics JSON, and `processing_notes.txt`.

## Required Outputs (`/app/output/`)

| File | Description |
|------|-------------|
| `valid_mask.tif` | Binary pixel quality mask (1=usable, 0=excluded), preserving input CRS and 200x200 dimensions |
| `ndvi.tif` | Normalized Difference Vegetation Index (Float32), excluded pixels as NaN |
| `emissivity.tif` | Land surface emissivity (Float32), excluded pixels as NaN |
| `lst_celsius.tif` | Land Surface Temperature in degrees Celsius (Float32), excluded pixels as NaN |
| `zonal_stats.json` | `{"zone_name": {"mean_lst_celsius": float, "min_lst_celsius": float, "max_lst_celsius": float, "valid_pixel_count": int}}` |
| `diagnostic_report.json` | `{"errors_found": [{"category": "string", "description": "string"}], "corrections_applied": [{"category": "string", "description": "string"}]}` |

All output GeoTIFFs must preserve EPSG:32618 and 200x200 dimensions.