The project at `/app/` implements four geometric predicates — `orient2d`, `orient3d`, `incircle`, and `insphere` — declared in `/app/predicates.hpp` and implemented in `/app/predicates.cpp`. An expansion arithmetic library is provided in `/app/expansion.hpp`.

The `orient2d` predicate is fully implemented and passes all tests. The other three predicates (`orient3d`, `incircle`, `insphere`) currently use only naive double-precision arithmetic and return **incorrect signs** for the near-degenerate test inputs in `/app/data/`.

Modify `/app/predicates.cpp` so that all four predicates return the correct sign (positive, negative, or zero) for every test case. The test data files contain 100 cases per predicate, each with coordinates and the expected sign (+1 or -1). These are adversarial near-degenerate inputs where naive floating-point evaluation produces the wrong sign due to catastrophic cancellation.

**Interface** (do not change):
- `void predicates_init()` — must be called once before any predicate
- `double orient2d(const double *pa, const double *pb, const double *pc)`
- `double orient3d(const double *pa, const double *pb, const double *pc, const double *pd)`
- `double incircle(const double *pa, const double *pb, const double *pc, const double *pd)`
- `double insphere(const double *pa, const double *pb, const double *pc, const double *pd, const double *pe)`

Each predicate returns a `double` whose **sign** encodes the geometric relationship. Only the sign matters for correctness.

**Build**: `make -C /app` produces `/app/test_predicates`.

**Verification**: `/app/test_predicates` reads the fixture files and prints `predicate: passed/total` for each. It exits 0 only when all 400 tests pass and prints `ALL TESTS PASSED`.

**Constraints**:
- Must compile with `g++ -O2 -std=c++17 -ffp-contract=off`.
- Do not modify `/app/expansion.hpp`, `/app/predicates.hpp`, `/app/main.cpp`, `/app/Makefile`, or any file under `/app/data/`.
- The expansion arithmetic library in `expansion.hpp` provides all necessary primitives: `Two_Sum`, `Two_Diff`, `Two_Product`, `Split`, `Fast_Two_Sum`, `Two_Two_Diff`, `fast_expansion_sum_zeroelim`, `scale_expansion_zeroelim`, `estimate`, and the error bound constants.
