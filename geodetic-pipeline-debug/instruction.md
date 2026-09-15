`/app/transforms.gie` contains 5 PROJ GIE transformation definitions, each with an intentional parameter error causing test vector failures. The PROJ toolchain (`gie`, `projinfo`, `cs2cs`, `cct`) is installed. Fix all 5 transformations so `gie /app/transforms.gie` reports zero failures.

The five transformations: oblique stereographic (Netherlands RD New), American polyconic (Brazil), Albers equal-area conic (Australia), Hotine oblique Mercator variant A (East Malaysia BRSO), and geocentric-to-geographic (WGS 84).

Produce these deliverables:

1. `/app/diagnostic_report.json` — JSON with `"task_instance_id"` (copied from `/app/calibration_data.json`) and `"pipelines"` array of 5 objects, each containing `pipeline_id` (1-5), `projection_type` (PROJ projection name, e.g. `"sterea"`), `error_description`, and `fix_description`.

2. `/app/calibration_results.json` — `/app/calibration_data.json` contains a unique `task_instance_id` and 5 random geographic coordinates, one per projection zone. For each coordinate, compute the forward transformation (geographic to projected for projections 1-4; geographic to geocentric for projection 5) using the corrected projection parameters via `cs2cs` or `cct`. Write JSON with `"task_instance_id"` and `"results"` array where each entry has `projection_id`, input coordinates, and output values (`easting`/`northing` for projections 1-4; `x`/`y`/`z` for projection 5).

3. `/app/roundtrip_validation.gie` — Valid GIE file with roundtrip stability tests (1000 iterations, 6mm tolerance for projections, 10mm for geocentric) covering all 5 fixed transformations. At least one `operation` and one `roundtrip` block per transformation.