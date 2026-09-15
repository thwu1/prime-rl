A synthetic Digital Elevation Model is provided at `/app/data/elevation.npy` (200x200 float64 numpy array, 30 m pixel resolution, NaN for nodata) along with sun position parameters at `/app/data/config.json` containing `sun_azimuth_degrees` (clockwise from north) and `sun_altitude_degrees` (above horizon). Grid metadata is at `/app/data/metadata.json`. The DEM grid has row 0 = north, row 199 = south. It contains an east-west escarpment, a Gaussian hill, and a rectangular nodata region representing a lake.

Build a pipeline that computes terrain cast shadows via ray-tracing through the DEM grid and produces a physically correct direct illumination map that accounts for both surface orientation (incidence angle from slope/aspect) and cast shadow occlusion.

## Required Outputs

- `/app/output/cast_shadow.npy` — uint8 numpy array. Value 1 = pixel is in cast shadow (terrain between pixel and sun blocks the direct beam), 0 = not in cast shadow, 255 = nodata. Same 200x200 shape as input.

- `/app/output/illumination.npy` — float32 numpy array. Direct beam illumination = cos(incidence angle) where the incidence angle is between the sun direction vector and the local surface normal, clamped to [0, 1]. Pixels in cast shadow or with self-shadow (surface faces away from sun) must have value 0. Nodata pixels must be NaN.

- `/app/output/analysis.json` — JSON with keys:
  - `cast_shadow_fraction`: fraction of valid pixels classified as cast shadow
  - `mean_illumination`: mean illumination over all valid pixels
  - `shadow_area_sq_m`: total cast-shadow area in square meters
  - `max_slope_degrees`: maximum terrain slope angle in degrees

Cast shadows must be determined by tracing rays from each DEM pixel toward the sun through the elevation grid — local slope/aspect alone is insufficient. Nodata cells must not block rays or be classified as shadowed. Python3 and numpy are available.