`/app/` contains a C++ project implementing a point-to-plane ICP (Iterative Closest Point) registration pipeline for 3D point clouds. The implementation uses Eigen3 for linear algebra and builds all algorithms from scratch: ASCII PCD file loading, brute-force nearest neighbor search, PCA-based surface normal estimation, and the iterative point-to-plane alignment loop.

The project compiles successfully but produces incorrect alignment results — the recovered rigid transformation does not match the known ground truth.

**Project structure**:
- `/app/CMakeLists.txt` — build configuration (requires Eigen3)
- `/app/src/main.cpp` — CLI entry point: loads two PCD files, runs registration, prints result
- `/app/src/point_cloud.hpp` / `point_cloud.cpp` — `PointCloud` struct and ASCII PCD file loader
- `/app/src/registration.hpp` — `RegistrationResult` struct and `alignPointToPlane()` interface
- `/app/src/registration.cpp` — the registration implementation (normal estimation, correspondence search, point-to-plane solve, iterative loop)
- `/app/generate_data.py` — generates synthetic PCD files with known ground truth (stdlib only, no pip deps)

**Build and run**:
```
mkdir -p /app/build && cd /app/build && cmake .. && make -j2
python3 /app/generate_data.py
/app/build/register_clouds /app/data/source.pcd /app/data/target.pcd
```

**Output format** (stdout): Four rows of 4 space-separated floats (the 4x4 homogeneous transformation matrix), followed by lines `FITNESS <float>`, `CONVERGED <0|1>`, `ITERATIONS <int>`.

Source and target clouds contain ~300 points on a curved 3D surface with Gaussian noise and ~5% outlier points. The ground truth transformation (rotation + translation) is written to `/app/data/ground_truth.txt` by the generator.

**Success criteria** (tested with two different randomly-generated datasets):
- Rotation error vs ground truth < 2 degrees
- Translation error vs ground truth < 0.04
- Fitness score (mean squared correspondence distance) < 0.01
- Algorithm reports convergence (`CONVERGED 1`)
- Rotation sub-matrix is approximately orthogonal
- Bottom row of output matrix is `[0 0 0 1]` within tolerance
