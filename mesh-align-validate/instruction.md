A 3D mesh geometry validation pipeline at `/app/mesh_validator.py` compares generated STL meshes against reference STLs and produces a JSON report with quality metrics and pass/fail checks. Usage:

```
python3 /app/mesh_validator.py <generated.stl> <reference.stl> /app/config.yaml
```

The pipeline outputs a JSON object to stdout with three top-level keys:

- `checks`: an object of boolean pass/fail results with keys `watertight`, `component_count`, `bounding_box`, `volume`, `chamfer`, `hausdorff`
- `metrics`: an object of numeric values (or null) with keys `chamfer_distance`, `hausdorff_95p`, `hausdorff_99p`, `icp_fitness`, `volume_ratio`, `generated_volume`, `reference_volume`
- `all_passed`: a boolean that is true only when every check passes

The pipeline has multiple independent bugs causing it to produce geometrically incorrect validation results. Sample mesh pairs are available at `/app/meshes/` (each pair has `pair_*_gen.stl` and `pair_*_ref.stl` files). Configuration thresholds are in `/app/config.yaml`.

Fix all bugs in `/app/mesh_validator.py` so that the following correctness requirements are satisfied. The command-line interface and JSON output schema described above must remain unchanged.

## Correctness requirements

**Watertight check**: The watertight check must handle meshes with duplicate or degenerate triangles. A mesh that is geometrically watertight but contains duplicate triangles must pass the watertight check (the pipeline must clean such artifacts before testing manifoldness). Meshes with genuinely missing faces must be detected as non-watertight.

**Volume check**: Volume computed via the divergence theorem is meaningless for open (non-watertight) meshes. The volume check must fail for any non-watertight generated mesh, even when the computed volume happens to fall within the configured threshold. When both meshes are watertight, volume comparison against `volume_threshold_percent` must be correct (e.g., a 50% volume mismatch must fail with a 2% threshold; a 1% mismatch must pass).

**Chamfer distance**: The chamfer distance must be bidirectional — the average of mean distances in both directions (generated-to-reference and reference-to-generated). Swapping which mesh is "generated" vs "reference" must produce approximately the same chamfer value. Identical meshes must produce a chamfer distance below 0.5mm and hausdorff distances below 1.0mm.

**Registration/alignment**: The FPFH+RANSAC+ICP registration pipeline must correctly align meshes that differ only by a spatial translation. Two identical meshes offset by 100mm on each axis must align to produce near-zero chamfer distance (< 0.5mm) and pass the bounding box check.

**Bounding box comparison**: After alignment, the axes of the generated mesh may be permuted relative to the reference. The bounding box extent comparison must be axis-invariant (i.e., compare sorted extents, not raw per-axis values) so that dimension mismatches are detected regardless of axis ordering.

**Component count**: Must accurately count connected components in the generated mesh and compare against the `expected_components` config value.