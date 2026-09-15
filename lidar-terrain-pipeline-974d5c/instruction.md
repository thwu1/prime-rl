A synthetic LiDAR point cloud is at `/app/data/survey.las`. It contains approximately 60,000 unclassified points (ASPRS Classification 0) covering a 200 m x 200 m area. The survey uses EPSG:32618 (UTM Zone 18N) but the LAS file has no embedded CRS. Survey metadata is in `/app/config.json`.

Run `python3 /app/generate_input.py` to produce `/app/data/survey.las` before processing. The generator is deterministic.

Create an executable `/app/process.sh` that reads the survey file and writes all outputs to `/app/output/`.

**Required output files and acceptance criteria:**

`ground.las` (or `ground.laz`) — Points classified as ground (ASPRS Class 2). Statistical outlier noise must be removed first. The file must contain between 10,000 and 60,000 points.

`non_ground.las` (or `non_ground.laz`) — All non-noise, non-ground points.

`dtm.tif` — Digital Terrain Model. Single-band GeoTIFF, approximately 1-meter resolution (pixel size within 0.5 m of 1.0 m), CRS EPSG:32618. Valid elevations must fall within 85–120 m. At least 80% of cells inside the survey bounds must contain data (no large nodata gaps). The DTM must approximate the true ground surface with RMSE below 2.0 m when sampled at interior points (10 m inset from edges).

`chm.tif` — Canopy Height Model. Single-band GeoTIFF, CRS EPSG:32618. Cell values represent the maximum height above the DTM surface. All values must be non-negative (clamp negatives to 0). Maximum canopy height must fall between 3 m and 30 m.

`slope.tif` — Slope raster derived from the DTM, in degrees. Single-band GeoTIFF, CRS EPSG:32618. Values must be non-negative and below 60 degrees.

`report.json` — JSON with this exact structure:
```json
{
  "total_points": <int, must be between 50000 and 80000>,
  "noise_points_removed": <int, must be > 100>,
  "ground_points": <int, must be between 10000 and 60000>,
  "non_ground_points": <int>,
  "bounding_box": {
    "minx": <float>, "maxx": <float>,
    "miny": <float>, "maxy": <float>,
    "minz": <float>, "maxz": <float>
  },
  "dtm": {
    "min": <float, must be in 85–100>,
    "max": <float, must be in 100–120>,
    "mean": <float>,
    "width_pixels": <int, must be > 50>,
    "height_pixels": <int, must be > 50>,
    "crs": "EPSG:32618"
  },
  "chm": {
    "max_height": <float, must be > 3.0>,
    "mean_height": <float>,
    "vegetation_coverage_pct": <float, 0–100>
  },
  "slope": {
    "max_degrees": <float, must be > 0>,
    "mean_degrees": <float, must be > 0>
  }
}
```

`vegetation_coverage_pct` is the percentage of valid CHM cells where height exceeds 0.5 m. Bounding-box X coordinates must be near 500000–500200; Y coordinates near 4500000–4500200.

Additional packages may be installed via `pip3` within `process.sh`.
