A finite element project in `/app/project/` contains a CalculiX input deck (`model.inp`) and a `notes.txt` file. The model represents a thick plate with an elliptical hole under pressure loading, built for verification against a published structural benchmark. It produces incorrect stress results due to multiple errors.

Diagnose all errors in the model, identify the benchmark, fix the model, and perform a mesh convergence study.

**Required output files:**

`/app/results.json` with exact schema:

```json
{
  "benchmark_id": "<string: standard benchmark identifier>",
  "errors": [
    {
      "line_number": "<int: line in original model.inp>",
      "original": "<string: erroneous content or '(missing)' for absent lines>",
      "corrected": "<string: correct content>",
      "category": "<string: exactly one of material | boundary_condition | loading>"
    }
  ],
  "convergence": [
    {
      "level": "<int: starting at 1>",
      "num_elements": "<int>",
      "num_nodes": "<int>",
      "sigma_yy_MPa": "<float>"
    }
  ],
  "final_sigma_yy_MPa": "<float>"
}
```

`/app/corrected.inp` -- Fixed CalculiX input file with all errors corrected. Must preserve the original mesh topology and element definitions from `/app/project/model.inp`.

`/app/convergence/` -- Directory containing CalculiX `.dat` output files named `level_1.dat`, `level_2.dat`, etc., one per refinement level. Each file must contain actual CalculiX solver output (non-empty).

**Acceptance criteria:**

- `benchmark_id` must correctly name the standard benchmark being modeled.
- All errors in the original model must be identified. The `errors` array must span at least two distinct `category` values.
- `/app/corrected.inp` will be parsed to verify physical correctness: elastic material constants (including Poisson's ratio) must match the benchmark specification, symmetry boundary conditions must be present on all required symmetry planes, and the applied distributed load must have the correct sign and magnitude. The corrected file must differ from the original.
- The convergence study must include at least 3 refinement levels with strictly increasing `num_elements`.
- `final_sigma_yy_MPa` must be within 5% of the benchmark's published reference value.
- Each convergence level must have a corresponding `.dat` file in `/app/convergence/` with size exceeding 100 bytes.
- Convergence data must show stress values trending toward the final result (earlier levels further from the converged value than later levels).

CalculiX (`ccx`) and Gmsh (`gmsh`) are installed. Python 3 with pip is available.
