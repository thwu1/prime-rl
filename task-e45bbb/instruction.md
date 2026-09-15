A warehouse robot navigation pipeline at `/app/` processes a 2D occupancy grid map, computes safety costmaps, resolves coordinate frame transforms, and plans a multi-waypoint route. The toolchain uses a Makefile, Python modules, SQLite, and jq.

Running `cd /app && make all` should execute the pipeline and produce `/app/results.json` and `/app/pipeline.db`. It currently fails.

Investigate the entire pipeline, identify and fix every defect, and verify `make all` succeeds with output conforming to `/app/schema/output_schema.json`.

After all fixes are applied, create `/app/defect_manifest.json` — a JSON array documenting each defect you corrected. Each entry must contain:
- `"file"`: path relative to `/app/` (e.g. `"src/module.py"` or `"Makefile"`)
- `"category"`: one of `"build"`, `"numeric"`, `"data-integrity"`, `"algorithmic"`, `"validation"`
- `"description"`: one-sentence summary of the defect and its correction

Key files:
- `/app/Makefile` — pipeline orchestration
- `/app/src/` — Python pipeline modules
- `/app/map/` — occupancy grid (PGM + YAML)
- `/app/config/nav_params.yaml` — robot and costmap parameters
- `/app/mission/waypoints.yaml` — start position and waypoints
- `/app/schema/output_schema.json` — required output structure