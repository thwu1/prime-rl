Point cloud data is stored in HDF5 format at `/app/data/`. Four HDF5 files correspond to two independent registration problems:

- Problem A: `source.h5`, `target.h5`
- Problem B: `source_b.h5`, `target_b.h5`

Use the pre-installed HDF5 CLI tools (`h5ls`, `h5dump` from `hdf5-tools`) to inspect each file's internal structure — discover dataset paths, shapes, dtypes, and attributes. The datasets are gzip-compressed, so raw binary reading will not work; use `h5py` (pre-installed system package) for programmatic access. A `metadata.json` file provides supplementary context.

For each problem, the target was generated from the source by applying an unknown similarity transformation (rotation R, translation t, uniform scale s), adding isotropic Gaussian noise, and contaminating with uniformly-distributed outlier points. Neither the outlier fraction nor the noise variance is known.

Implement a probabilistic registration algorithm from scratch that recovers the transformation for Problem A and writes the result to `/app/result.json`:

```json
{
  "rotation_matrix": [[r00, r01, r02], [r10, r11, r12], [r20, r21, r22]],
  "translation": [tx, ty, tz],
  "scale": s
}
```

Convention: `target_inliers ≈ s * (source @ R.T) + t + noise`

**Generalization:** Your Python registration script in `/app/` will be automatically re-executed on Problem B via string substitutions: `source.h5` → `source_b.h5`, `target.h5` → `target_b.h5`, `result.json` → `result_b.json`. The modified copy runs as a separate process to produce `/app/result_b.json`. Structure your script so these replacements yield a valid, runnable program.

**Accuracy thresholds (verified automatically):**
- Problem A: rotation angular error < 2°, translation L2 error < 0.1, scale relative error < 5%
- Problem B: rotation angular error < 3°, translation L2 error < 0.15, scale relative error < 5%
- R must be a proper rotation matrix: R^T R ≈ I and det(R) ≈ 1 (tolerance 1e-3)
- Alignment quality (Problem A): applying the recovered transformation must place at least 70% of transformed source points within Euclidean distance 0.3 of their nearest target point

**Constraints:**
- `numpy`, `scipy`, and `h5py` are pre-installed. HDF5 CLI tools (`h5ls`, `h5dump`) are available for data exploration.
- Registration libraries (`probreg`, `pycpd`, `open3d.pipelines.registration`, or equivalent) are **forbidden** — presence of these imports in any `/app/*.py` file will cause verification failure.
- The transformation must be derived algorithmically from the point cloud geometry; hardcoded values will be detected.