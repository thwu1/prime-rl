Implement a rotation averaging solver that recovers globally consistent camera orientations from noisy pairwise relative rotation measurements, some of which are outliers.

`/app/pose_graph.json` contains a camera pose graph:
- `num_cameras`: number of cameras (integer)
- `edges`: list of relative rotation measurements, each with `i`, `j` (camera indices), `R_ij` (3×3 rotation matrix as nested list, convention: `R_j ≈ R_ij @ R_i`), and `weight` ∈ (0, 1]

Approximately 12% of edges carry incorrect (outlier) rotations with arbitrary orientations.

Create a Python script at `/app/solver.py` that reads `/app/pose_graph.json`, solves for globally consistent rotations using robust optimization on the SO(3) manifold, identifies outlier measurements, and writes results to `/app/output/results.json`. The script must be runnable via `python3 /app/solver.py` and must exit with return code 0.

## Output Format

`/app/output/results.json` must be valid JSON with the following schema:

```json
{
  "rotations": {"0": [[r00,r01,r02],[r10,r11,r12],[r20,r21,r22]], "1": ..., ...},
  "outlier_edges": [[i1,j1], [i2,j2], ...]
}
```

- `rotations`: mapping from camera index as a **string key** (`"0"`, `"1"`, ..., `"N-1"`) to a 3×3 rotation matrix (list of 3 lists of 3 floats). Every camera index from `0` to `num_cameras - 1` must have an entry.
- `outlier_edges`: list of 2-element lists `[i, j]` where each element is numeric (int or float), identifying edges deemed outliers.

## Acceptance Criteria

**Rotation validity** — each output rotation must be a valid SO(3) element:
- Orthogonality: `R @ R^T` must equal the 3×3 identity matrix within absolute tolerance 1e-3.
- Determinant: `det(R)` must equal +1 within absolute tolerance 1e-3.

**Rotation accuracy** — the solution is defined up to a global rotation (gauge freedom). After right-Procrustes alignment on SO(3) (finding G that minimizes the sum of squared Frobenius norms of `R_gt[i] - R_est[i] @ G`), angular errors are measured via the geodesic distance:
- Mean angular error across all cameras must be below 2 degrees.
- Maximum angular error for any single camera must be below 5 degrees.

**Outlier detection quality**:
- Precision ≥ 0.6 — at least 60% of reported outlier edges must be true outliers.
- Recall ≥ 0.6 — at least 60% of true outlier edges must be detected.
- Outlier edges are compared as unordered pairs `(min(i,j), max(i,j))`.

**Generalization** — the solver will be evaluated on the provided pose graph **and** on an independently generated pose graph with the same structure and conventions. It must produce valid, accurate results on both. Do not hardcode answers for a specific input.