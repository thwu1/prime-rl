The file `/app/incircle_naive.h` contains a 2D incircle predicate that produces incorrect results on certain floating-point inputs. The test harness `/app/test_incircle.cpp` exposes these failures. Libraries `libmpfr-dev` and `libgmp-dev` are installed in the environment.

Create three files:

**`/app/incircle.h`** — Header-only C++ replacement providing:

```cpp
namespace robust {
  int incircle(const double* a, const double* b, const double* c, const double* d);
  int incircle(double ax, double ay, double bx, double by,
               double cx, double cy, double dx, double dy);
}
```

Each pointer addresses two consecutive doubles `{x, y}`. Returns `+1` if `d` is inside the circle through `a,b,c` (counter-clockwise), `-1` if outside, `0` if cocircular. Must produce correct signs on all inputs, including adversarial configurations where the true determinant magnitude is less than `1e-30` times the largest intermediate product. Must not use GMP, MPFR, Boost.Multiprecision, or any external arbitrary-precision library. Must not heap-allocate on the common (non-degenerate) code path.

**`/app/verify_mpfr.cpp`** — Standalone verification program that:
- Computes incircle results at 256-bit precision or higher using MPFR as an independent oracle
- Tests the implementation in `/app/incircle.h` on at least 200 point configurations spanning: random, nearly-cocircular (perturbation < 1e-10 relative to radius), large-coordinate (> 1e12), exactly cocircular, and collinear inputs
- Prints `MPFR_VERIFICATION_PASSED` to stdout and exits 0 if all results match the oracle; otherwise prints `MPFR_VERIFICATION_FAILED` with details and exits non-zero

**`/app/CMakeLists.txt`** — CMake build file producing two targets:
- `test_incircle` from `test_incircle.cpp` (standard C++ only)
- `verify_mpfr` from `verify_mpfr.cpp` linked against MPFR and GMP
- Both targets must compile with `-O2 -frounding-math`

Build and test:
```
cmake -B /app/build -S /app && cmake --build /app/build
/app/build/test_incircle
/app/build/verify_mpfr
```

All three commands must succeed. Do not modify `test_incircle.cpp` or `incircle_naive.h`.

