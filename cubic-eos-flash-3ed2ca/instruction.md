The C++ project at `/app/` implements a multi-component Peng-Robinson equation of state isothermal flash calculator. The project uses CMake (`cmake -B build && cmake --build build`) and consists of source files under `/app/src/`. The implementation contains defects in its build configuration, thermodynamic computations, and phase identification logic that must be diagnosed and corrected.

Running `/app/build/flash_solver` must write `/app/results.txt` with correct output for all six embedded test problems. The problems include both two-phase VLE systems and single-phase supercritical states.

**Correctness criteria for two-phase results:**
- Equal-fugacity: |ln(phi\_L,i) + ln(x\_i) - ln(phi\_V,i) - ln(y\_i)| < 1e-5 for every component
- Material balance: |z\_i - (1-V)\*x\_i - V\*y\_i| < 1e-6
- Normalization: |sum(x\_i) - 1| < 1e-8 and |sum(y\_i) - 1| < 1e-8
- Convergence: `STATUS` is `converged`; 0 < V < 1
- Reported fugacity coefficients must agree with an independent Peng-Robinson computation to within 1e-5

**Correctness criteria for single-phase results:**
- `PHASE` is `single_phase`
- Reported fugacity coefficients match an independent PR computation of the feed to within 1e-6

**Output format** (`/app/results.txt`):
Each problem block begins with `PROBLEM: <name>` and ends with `END`. Fields are `KEY: value`.
All blocks: `STATUS`, `PHASE`, `NC`, `COMP` (space-separated indices), `FEED`.
Two-phase: `V`, `LIQUID`, `VAPOR`, `LN_PHI_L`, `LN_PHI_V`, `Z_L`, `Z_V`.
Single-phase: `LN_PHI`, `Z_FACTOR`.
All floating-point values at least 12 significant digits.

Component database and binary interaction parameters are in `/app/src/component_db.h`. Do not change the output format, problem definitions, or component data.
