Two cameras observe the same 3D scene. Monocular depth predictions are available for each view, but each prediction suffers from an unknown per-view affine distortion: `true_depth = a * predicted_depth + b` with unknown `(a, b)` per view. Given 2D point correspondences and their corrupted depth observations across both views, recover the relative camera pose (rotation matrix R, translation vector t).

`/app/problem_spec.py` contains the mathematical model (distance consistency constraints, the resulting polynomial structure in the unknown affine parameters) and the required function signatures. Test scenarios with ground truth are in `/app/data/`.

The C source file `/app/coeffgen.c` implements the polynomial coefficient computation from point correspondences and depths. Your solver must compile this into a shared library at `/app/libcoeffgen.so` and call it via Python's foreign function interface — do not reimplement the coefficient generation in pure Python.

Deliver:

- `/app/libcoeffgen.so` — compiled shared library from `/app/coeffgen.c`
- `/app/solver.py` — implements all four functions specified in `/app/problem_spec.py`, correctly handles data with outlier correspondences, and produces numerically accurate pose estimates