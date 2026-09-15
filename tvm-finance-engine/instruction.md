The financial analytics library at `/app/tvm.py` implements Time Value of Money calculations (future value, present value, payment schedules, IRR, NPV, MIRR, etc.) with optional native C acceleration for the NPV hot path. A quick validation script at `/app/test_quick.py` reveals several failures when run with `python3 /app/test_quick.py`. However, this script is not comprehensive — additional defects exist that only manifest under specific parameter combinations, edge cases, or payment timing modes.

The library includes a native C accelerator at `/app/native/` intended to provide a fast path for NPV computation. The C source (`discount.c`), build system (`Makefile`), and Python ctypes integration are all present but non-functional — the shared library does not build, and the ctypes binding code in `tvm.py` has defects that prevent correct operation even if the library were loadable.

Debug and repair the full system so that:

1. All existing TVM functions (`fv`, `pv`, `pmt`, `nper`, `ipmt`, `ppmt`, `rate`, `irr`, `npv`, `mirr`) produce numerically correct results for all valid inputs, including edge cases and all `when` parameter modes.

2. The stub functions `xnpv` and `xirr` are fully implemented. `xnpv(rate, cashflows, dates)` computes net present value for cashflows on arbitrary `datetime.date` dates using actual/365 day-count convention. `xirr(cashflows, dates)` finds the annual rate where `xnpv` equals zero.

3. Edge cases return appropriate sentinel values: `NaN` for infeasible solutions (same-sign cashflows in IRR/MIRR, non-convergent rate solver, mathematical singularities like rate == -1 in NPV), `inf` where mathematically justified.

4. Functions that accept `decimal.Decimal` inputs (`fv`, `pv`, `pmt`, `ipmt`, `ppmt`, `rate`) return `Decimal` results when given `Decimal` arguments. The `rate` solver must perform its iteration in the caller's numeric type.

5. Cross-function algebraic identities hold: `pmt(r,n,pv) == ipmt(r,per,n,pv) + ppmt(r,per,n,pv)` for all valid periods, and `npv(irr(v), v) ≈ 0` for mixed-sign cashflow vectors.

6. The native C accelerator builds successfully (`make -C /app/native` produces `/app/native/libdiscount.so`), the ctypes integration in `tvm.py` loads and uses it correctly, and `npv()` delegates to the native backend for scalar-rate computations. The native implementation must handle all edge cases identically to the pure-Python fallback.

7. Array inputs broadcast following numpy conventions. Scalar inputs return scalars.

Write the corrected module to `/app/tvm.py`, fix the C source and Makefile at `/app/native/`, and ensure the full system passes validation.
