Binary STL mesh files representing pairs of candidate and reference 3D geometries are in `/app/meshes/`. Pair assignments, evaluation parameters, and the required output schema are defined in `/app/config.json`.

Build `/app/mesh_eval.py` — a pipeline that quantifies the geometric similarity between each candidate mesh and its reference using the metrics and parameters specified in the config. Some candidate meshes contain intentional geometric defects that must be detected, repaired where possible, and flagged in the output.

Write results to `/app/results.json` conforming exactly to the output schema in `/app/config.json`. Results must be deterministic across runs.