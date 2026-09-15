A partially implemented C++ header-only library for computing uniform boundaries used in anytime-valid sequential inference is at `/app/uniform_boundaries.h`. It uses Boost.Math special functions and implements mixture supermartingale boundaries from the Howard-Ramdas framework for time-uniform confidence sequences.

The library contains subtle mathematical bugs in some function implementations and unimplemented stubs (functions that throw `std::runtime_error`) for others. A test driver at `/app/test_runner.cpp` verifies all boundary functions against known reference values (from a validated R implementation) with tolerance 1e-5.

Build and run:
```
cd /app && mkdir -p build && cd build && cmake .. && make && ./test_runner
```

Fix all bugs and implement all stubs in `/app/uniform_boundaries.h` so that every test passes.

**Constraints:**
- All modifications must be in `/app/uniform_boundaries.h` only
- Do not modify `test_runner.cpp` or `CMakeLists.txt`
- All functions must match reference values within 1e-5 tolerance
- The library must remain header-only with inline implementations

**Boundary types present** (some correct, some buggy, some stubbed):
- Normal mixture (one-sided and two-sided)
- Gamma-exponential mixture
- Gamma-Poisson mixture
- Beta-binomial mixture (one-sided and two-sided)
- Polynomial stitching bound
- Bernoulli confidence interval (uses bisection root-finding over the beta-binomial mixture supermartingale)

**Success criteria:** `./test_runner` exits with code 0, printing `ALL TESTS PASSED`.
