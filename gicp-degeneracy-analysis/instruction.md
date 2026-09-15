Five 3D point cloud scan pairs are stored in `/app/scans/scan_1/` through `/app/scans/scan_5/`. Each directory contains:
- `target.txt` — Nx3 point coordinates (space-separated, one point per line)
- `source.txt` — Mx3 point coordinates (same format)

Source points relate to the target frame by an unknown rigid transformation T ∈ SE(3): `p_target = T · p_source`. The `small_gicp` Python package is pre-installed, providing GICP-based registration with access to the 6×6 registration Hessian (information matrix) through the result object's `.H` attribute.

These scan pairs capture geometrically diverse 3D scenes. Some exhibit structural properties that render the registration problem ill-conditioned — the scene geometry may leave certain rigid-body degrees of freedom poorly observable from point correspondences alone. You must build a registration and observability analysis pipeline that produces accurate alignments where possible, diagnoses ill-conditioned registrations through Hessian eigenanalysis, and characterizes each scene's geometric constraints.

Write results for each scan pair to `/app/results/scan_N/` (N = 1..5):

**`transform.json`** — The estimated 4×4 rigid transformation:
```
{"matrix": [[r00, r01, r02, tx], [r10, r11, r12, ty], [r20, r21, r22, tz], [0, 0, 0, 1]]}
```
The 3×3 rotation block must be a valid SO(3) matrix (orthogonal, determinant 1). Bottom row must be `[0, 0, 0, 1]`.

**`hessian_eigenvalues.json`** — The 6 eigenvalues of the registration Hessian, sorted ascending:
```
{"eigenvalues": [e1, e2, e3, e4, e5, e6]}
```
All eigenvalues must be non-negative (the Hessian is symmetric PSD).

**`classification.json`** — Degeneracy classification based on eigenvalue analysis:
```
{"is_degenerate": <bool>, "condition_number": <float>, "degenerate_dof_count": <int>}
```
- `condition_number` = ratio of the smallest to the largest Hessian eigenvalue
- `degenerate_dof_count` = number of eigenvalues falling below 1% of the maximum eigenvalue
- `is_degenerate` = `true` when `degenerate_dof_count > 0`

Degenerate scans must have `condition_number < 0.01`. Non-degenerate scans must have eigenvalue ratio (min/max) exceeding 0.005, and this ratio must be strictly larger than the ratio of any degenerate scan.

**`diagnosis.json`** — Scene characterization and quality assessment:
```
{"scene_type": <str>, "registration_reliable": <bool>, "num_well_constrained_dofs": <int>, "corrective_strategy": <str or null>}
```
- `scene_type`: inferred dominant geometry label (e.g., `"planar"`, `"cylindrical"`, `"multi_planar"`, `"box"`)
- `registration_reliable`: `true` only when all 6 DOFs are well-constrained (not degenerate)
- `num_well_constrained_dofs`: equals `6 - degenerate_dof_count`
- `corrective_strategy`: `null` for fully reliable registrations; for degenerate scans, a string describing the mitigation applied (e.g., `"multi_pass_refinement"`)

**Quality expectations:**
- Non-degenerate scenes: rotation error < 5° and translation error < 0.35 units relative to the true alignment.
- Degenerate scenes: DOFs that ARE geometrically constrained must still be accurately estimated — constrained translation components should have < 0.30 units error.
- Non-degenerate eigenvalue ratios (min/max) must exceed 0.005 and must be strictly larger than those of any degenerate scene.