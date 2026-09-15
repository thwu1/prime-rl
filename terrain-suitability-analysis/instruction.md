You are given geospatial datasets assembled from external sources for a terrain suitability assessment. The data has not been quality-validated and may contain errors introduced during acquisition, processing, or format conversion.

## Input data

- `/app/dem.tif` — Digital Elevation Model (EPSG:32633, UTM Zone 33N, 30 m resolution, 300×300 pixels)
- `/app/control_points.csv` — Ground control elevation measurements from a GPS survey (columns: `id`, `easting`, `northing`, `elevation_m`; coordinates in EPSG:32633)
- `/app/exclusion_zones.geojson` — Restricted areas to exclude from the analysis
- `/app/site_spec.json` — Site selection criteria and scoring parameters

## Task

Audit all input datasets for quality issues. Use the ground control measurements and any other appropriate validation methods to identify and correct problems in the data before proceeding with analysis. Produce a corrected DEM, compute terrain derivatives from it, apply the site suitability criteria defined in the specification, identify contiguous candidate regions, and rank them according to the scoring scheme in the specification.

## Required outputs

Rasters in `/app/output/` (must preserve original DEM dimensions and CRS):
- `dem_calibrated.tif` — quality-corrected DEM with proper nodata handling
- `slope.tif` — slope in degrees
- `aspect.tif` — aspect in degrees clockwise from north
- `tri.tif` — terrain ruggedness index
- `suitability.tif` — binary mask (1 = suitable, 0 = unsuitable)

Analysis results at `/app/results.json`:
```json
{
  "total_suitable_pixels": "<int>",
  "total_suitable_area_m2": "<float>",
  "num_suitable_regions": "<int>",
  "top_regions": [
    {
      "rank": "<int>",
      "region_id": "<int>",
      "pixel_count": "<int>",
      "area_m2": "<float>",
      "centroid_utm_e": "<float>",
      "centroid_utm_n": "<float>",
      "centroid_lon": "<float>",
      "centroid_lat": "<float>",
      "mean_elevation": "<float>",
      "mean_slope": "<float>",
      "mean_aspect": "<float>",
      "aspect_uniformity": "<float>",
      "score": "<float>"
    }
  ],
  "optimal_region_id": "<int>"
}
```