A flow measurement calibration system at `/app/` combines a C shared library for orifice plate computations with Python ctypes bindings and pure-Python IEC 60534 control valve sizing. The system is currently non-functional due to build and computational defects.

**Files:**
- `/app/Makefile` — builds `libflowcore.so` from C source in `/app/src/`
- `/app/src/flowcore.c` and `/app/src/flowcore.h` — C implementations of orifice plate discharge coefficient, expansibility factor, and iterative flow rate solver
- `/app/flowcal.py` — Python module providing ctypes wrappers for the C library and pure-Python valve sizing
- `/app/run_calibration.py` — calibration pipeline reading reference data from SQLite; orifice processing is implemented, valve processing is stubbed
- `/app/config.toml` — tolerance and output settings
- `/app/data/reference_data.sql` — SQLite schema and reference test data

**Required outcome:**

Produce a working system where `cd /app && make && python3 run_calibration.py` generates `/app/results.json` conforming to:

```json
{
  "test_results": [
    {
      "id": "<string>",
      "category": "<orifice_C|orifice_eps|orifice_flow|valve_liquid|valve_gas>",
      "computed": "<float>",
      "expected": "<float>",
      "error_pct": "<float: 100 * |computed - expected| / |expected|>",
      "status": "<pass|fail>"
    }
  ],
  "summary": {
    "total": "<int>",
    "passed": "<int>",
    "failed": "<int: must be 0>"
  }
}
```

A test passes when `error_pct` is below `tolerance_pct` in `/app/config.toml`. All test cases must pass.

**Function signatures in `/app/flowcal.py` (must be preserved):**
- `orifice_discharge_coefficient(D, Do, rho, mu, m, taps="corner")` → float
- `orifice_expansibility(D, Do, P1, P2, k)` → float
- `solve_orifice_flow_rate(D, Do, P1, P2, rho, mu, k, taps="corner")` → float
- `size_liquid_valve(rho, Psat, Pc, mu, P1, P2, Q, D1=None, D2=None, d=None, FL=0.9, Fd=1.0)` → float
- `size_gas_valve(T, MW, mu, gamma, Z, P1, P2, Q, D1=None, D2=None, d=None, FL=0.9, Fd=1.0, xT=0.7)` → float

**Constraints:**
- The C shared library must compile and link correctly via the Makefile
- Orifice discharge coefficient must be correct for tap types `"corner"`, `"D"`, and `"flange"`
- The C library and the Python ctypes layer must agree on the tap type encoding defined in `flowcore.h`
- Valve sizing must handle equal pipe/valve diameters (no piping correction) and differing diameters (iterative piping geometry correction), for both choked and non-choked flow regimes
- Functions are verified against reference values at relative tolerance 1e-4
- The calibration database is initialized at `/app/data/calibration.db` from the SQL file
- The report must include entries for all five categories
- Summary must be consistent: `total` equals entry count, `passed + failed` equals `total`
