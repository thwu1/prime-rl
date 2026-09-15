A multi-file C++ aqueous geochemistry equilibrium solver at `/app/` computes speciation for H2O-Na-Cl-Ca-C-S systems with temperature-dependent thermodynamics and mineral phase equilibrium. The source files (`thermo.hpp`, `activity.hpp/cpp`, `solver.hpp/cpp`, `main.cpp`, `CMakeLists.txt`) contain multiple interacting bugs that prevent building and producing correct results. Five problem input files (`/app/problem_1.txt` through `/app/problem_5.txt`) define test cases at varying compositions and temperatures.

Build: `cd /app && mkdir -p build && cd build && cmake .. && make`

Run: `/app/build/geqsolve /app/problem_N.txt /app/results_N.txt` for N=1..5.

**Output** (`results_N.txt`): space-delimited key-value pairs, one per line. Required keys: `pH`, `ionic_strength`, `m_H`, `m_OH`, `m_Na`, `m_Cl`, `m_Ca`, `m_SO4`, `m_CO2`, `m_HCO3`, `m_CO3`, `m_CaCO3aq`, `m_NaClaq`, `m_CaSO4aq`, `charge_balance`, `calcite_SI`, `gypsum_SI`, `n_calcite`, `n_gypsum`, `converged`, `iterations`.

**Acceptance criteria** (all five cases):
- `converged 1`.
- `|charge_balance| < 1e-5` mol/kgw.
- Element mass balances (Na, Cl, Ca, C, S): relative error < 0.1%, accounting for precipitated mineral amounts in relevant element totals.
- Six equilibrium-constant relationships (H2O dissociation, CO2 1st dissociation, HCO3- 2nd dissociation, CaCO3(aq) complexation, NaCl(aq) ion pairing, CaSO4(aq) complexation): `|log10(Q) - log10(K(T))| < 0.02`, with Q computed using activity coefficients consistent with the model specified in the source headers.
- All molalities and mineral amounts >= 0.
- If `n_mineral > 0`: `|SI| < 0.05`. If `n_mineral = 0`: `SI < 0.05`.
- Reported `calcite_SI` and `gypsum_SI` consistent with computed molalities and activity coefficients (within 0.1).
- Case 5 must show calcite precipitation (`n_calcite > 0`).

**Physical ranges**: Case 1: pH 4-9, I 0.005-0.02. Case 2: pH 5-10, I 0.08-0.15. Case 3: pH 4-8.5, I 0.08-0.25. Case 4: pH 4-8.5, I 0.08-0.15. Case 5: pH 4-8, I 0.3-0.7.

Do not alter thermodynamic constants, species set, reaction definitions, input format, or problem files.
