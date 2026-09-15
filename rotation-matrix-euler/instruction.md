A 3D rotation math library at `/app/` provides `Vec3`, `Quat`, and `Mat3` types for rotation operations. The project uses a CMake build system at `/app/CMakeLists.txt` but the build configuration has errors that prevent compilation.

The library implementation at `/app/rotation_math.cpp` contains mathematical defects across multiple rotation operations. Identify and fix all issues by analyzing test failures — the defects are not documented.

Beyond fixing existing code, implement three operations declared but stubbed in the source:

**`Vec3 Mat3::log_rotation() const`** — Compute the rotation vector (axis scaled by angle in radians) for this rotation matrix. Returns the zero vector for identity. Must produce finite results for 180-degree rotations and near-zero angles.

**`double Mat3::geodesic_distance(const Mat3& other) const`** — Geodesic distance in radians between two rotation matrices on SO(3). Non-negative, zero for identical rotations, symmetric, and satisfies the triangle inequality.

**`void Quat::swing_twist_decompose(const Vec3& twist_axis, Quat& out_swing, Quat& out_twist) const`** — Decompose this rotation into twist (rotation about the unit-length `twist_axis`) and swing (perpendicular rotation) satisfying `*this ≈ swing * twist`. Both outputs are unit quaternions. The twist quaternion's imaginary part must be parallel to `twist_axis`; the swing's imaginary part must be perpendicular to it.

**Storage:** `Mat3` stores `rows[3]` row-major. Column `i` = `Vec3(rows[0][i], rows[1][i], rows[2][i])`.

**Build and test:**
```
cd /app && mkdir -p build && cd build && cmake .. && make
./test_runner
```

All tests must report PASS with exit code 0. The test source is at `/tests/test_rotation.cpp`.

**Files to modify:** `/app/CMakeLists.txt`, `/app/rotation_math.cpp`, `/app/rotation_math.hpp` as needed.
