The file `/app/src/ik.cpp` contains a stub implementation of `inverse()` declared in `/app/include/manipulator.h`. This function must compute all valid analytic inverse kinematics solutions for a 6-DOF serial manipulator with a spherical wrist.

A complete forward kinematics implementation is in `/app/src/fk.cpp`. The robot's DH parameters and offset transform conventions are documented in `/app/include/manipulator.h` and applied within the FK code.

## Build System

The project's `/app/CMakeLists.txt` defines a shared library `manipulator_core` (built from `fk.cpp` and `ik.cpp`) and an executable (built from `main.cpp`) that dynamically links against it. The CMake configuration contains errors that prevent successful compilation and runtime execution. Diagnose and fix these issues, then configure and build into `/app/build/`:

```
cd /app && cmake -B build && cmake --build build
```

The resulting binary must be at `/app/build/manipulator` and must dynamically link against `libmanipulator_core.so`.

## IK Contract

`int inverse(const double* T, double* q_sols, double q6_des)` must:

- Accept a 4x4 row-major homogeneous transform (`double[16]`) representing the end-effector pose in the base frame.
- Write all geometrically valid joint-angle solutions into `q_sols` (pre-allocated for 8x6 doubles) and return the count (0-8).
- Every returned solution must satisfy `||forward(q_sol) - T||_F < 1e-6`. Do not emit invalid or unreachable configurations.
- Produce every joint angle in `[0, 2*PI)`.
- Handle wrist singularities (`sin(q5)` near 0) by using `q6_des` for the indeterminate q6, still returning valid solutions.
- For every reachable pose, at least one solution must be found (return count > 0).

The binary supports `--fk q1..q6` and `--ik T0..T15` modes for testing individual configurations.

## Verification

```
/app/build/manipulator --verify 1000
```

must print `STATUS: ALL PASSED` with zero failures and zero missing solutions.

Full test suite: `pytest /tests/test_state.py -v`
