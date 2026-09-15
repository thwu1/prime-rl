An Abaqus-format finite element input deck for the NAFEMS LE10 thick plate benchmark is provided at `/app/le10_abaqus.inp`. CalculiX (`ccx`) is installed in the environment. The Abaqus input uses implicit mesh generation features (`*NCOPY`, `*ELGEN`, `*NSET ... GENERATE`) that CalculiX does not support natively.

Create `/app/pipeline.py` (invoked as `cd /app && python3 pipeline.py`) that produces a solvable CalculiX model from the Abaqus input, runs CalculiX to solve it, and extracts the direct stress component SYY at the NAFEMS LE10 measurement point D (located on the loaded top surface at the inner boundary) from the solver results.

The pipeline must produce:

1. `/app/le10_ccx.inp` — fully expanded CalculiX input with explicit node and element definitions (no implicit mesh generation keywords remain)
2. `/app/le10_ccx.frd` — CalculiX results file from a successful solve
3. `/app/results.json` with this schema:

```json
{
  "num_nodes": <int>,
  "num_elements": <int>,
  "point_D_node_id": <int>,
  "point_D_coords_m": [<float>, <float>, <float>],
  "sigma_y_Pa": <float>,
  "sigma_y_MPa": <float>,
  "relative_error_pct": <float>
}
```

`relative_error_pct` is `|sigma_y_MPa - (-5.38)| / 5.38 * 100`, where -5.38 MPa is the published NAFEMS reference for SYY at point D.

Success criteria:

- `/app/le10_ccx.inp` contains no `*NCOPY` or `*ELGEN` keywords
- `/app/le10_ccx.frd` is a valid CalculiX output file containing coordinate and stress result blocks
- `/app/results.json` exists with all required fields
- `num_nodes` and `num_elements` match the actual node and element counts parsed from `/app/le10_ccx.inp`
- `sigma_y_Pa` matches the SYY value at `point_D_node_id` as independently extracted from `/app/le10_ccx.frd`
- `point_D_node_id` identifies a node within 0.001 m of point D in the `.frd` coordinate data
- `sigma_y_MPa` is within 15% of the NAFEMS reference and is negative
- `sigma_y_Pa` / `sigma_y_MPa` approximates 1e6
