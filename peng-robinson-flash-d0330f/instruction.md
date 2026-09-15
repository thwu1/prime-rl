The `/app/` directory contains a thermodynamic equation-of-state toolkit combining a C shared library (`cubic_core.c`, built via `Makefile` into `libcubic.so`) with a Python ctypes module (`eos_engine.py`). Component parameters are in `/app/params.toml`. The system is currently non-functional.

Produce a working system satisfying all requirements below.

**C shared library**: `/app/libcubic.so` must be buildable from source in `/app/` and export working `eos_pressure` and `eos_solve_Z` symbols. `eos_pressure(V, T, n, a_mix, b_mix, delta1, delta2, R)` must return P = nRT/(V−nb) − n²a\_mix/((V+nb·δ₁)(V+nb·δ₂)). `eos_solve_Z(A, B, delta1, delta2, roots)` must return sorted compressibility factor roots of the generic cubic EOS. The library must be usable via Python ctypes.

**Python module**: `/app/eos_engine.py` must export `PengRobinson`, `SRK`, and `load_params`.

Public interface (identical for both EOS classes):

```
__init__(Tc, Pc, omega, kij=None)      Tc [K], Pc [Pa], omega [-], kij NxN
pressure(V, T, z)                       V [m³] total, T [K], z mole amounts → P [Pa]
volume(p, T, z, phase='vapor')          → V [m³]
fugacity_coefficients(p, T, z, phase)   → list of φᵢ
tp_flash(p, T, z)                       → {'beta': float, 'x': list, 'y': list} or None
bubble_pressure(T, z)                   → P [Pa], z = mole fractions
dew_pressure(T, z)                      → P [Pa]
a_res(V, T, z)                          → dimensionless residual Helmholtz Aʳᵉˢ/(nRT)
enthalpy_departure(p, T, z, phase)      → H_dep [J/mol]
entropy_departure(p, T, z, phase)       → S_dep [J/(mol·K)]
```

PR: Ωa=0.45724, Ωb=0.07780, δ₁=1+√2, δ₂=1−√2. SRK: Ωa=0.42748, Ωb=0.08664, δ₁=1, δ₂=0. R = 8.314462618153241 J/(mol·K). Van der Waals one-fluid mixing rules with binary interaction parameter kij.

`load_params(filepath)` → `(names, Tc_list, Pc_list, omega_list, kij_matrix)` parsed from the TOML format used in `/app/params.toml`.

**Success criteria**:
- P/V roundtrip: |P(V(p,T,z,φ),T,z) − p|/p < 1e-10
- Flash material balance: |zᵢ − (1−β)xᵢ − βyᵢ| < 1e-8
- Flash fugacity equality: |φ\_L,i·xᵢ − φ\_V,i·yᵢ|/max(φ\_V,i·yᵢ, 1e-15) < 1e-6
- a\_res relative tolerance 1e-6 against reference oracle
- tp\_flash returns None outside two-phase envelope
- At bubble pressure β<0.02; at dew pressure β>0.98; P\_bubble > P\_dew
- H\_dep − T·S\_dep = RT·(a\_res + Z − 1 − ln Z), where Z = PV/(nRT)
- Handle 2–5 component systems
