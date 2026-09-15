A Peng-Robinson (PR) flash calculator exists at `/app/pr_flash.py`. It is intended to perform isothermal PT flash calculations for multicomponent hydrocarbon mixtures but produces incorrect phase equilibrium results for several chemical systems. The Python package `thermo` (installable via pip) provides reference implementations via `thermo.eos_mix.PRMIX` and `thermo.eos_mix.SRKMIX`.

Diagnose and repair `/app/pr_flash.py` so its PR EOS results match the `thermo` reference. Then extend the module to also support SRK (Soave-Redlich-Kwong) EOS and bubble-point pressure calculation. The final module must be self-contained: only the standard library and `scipy` are permitted as runtime dependencies.

**Required API**

```python
pt_flash(Tcs, Pcs, omegas, zs, T, P, kijs=None, eos="PR") -> dict
```

Parameters: critical temperatures `Tcs` [K], critical pressures `Pcs` [Pa], acentric factors `omegas`, feed mole fractions `zs`, temperature `T` [K], pressure `P` [Pa], optional binary interaction parameter matrix `kijs` (default zeros), EOS type `eos` (`"PR"` or `"SRK"`). Return dict with keys: `V_over_F` (0-1 two-phase, -1.0 liquid, 2.0 vapor), `xs`, `ys`, `phis_l`, `phis_g`, `K_values`, `H_dep_l`, `H_dep_g`, `S_dep_l`, `S_dep_g`. Absent-phase fields are `None`.

```python
bubble_pressure(Tcs, Pcs, omegas, xs, T, kijs=None, eos="PR") -> dict
```

Compute bubble-point pressure for liquid composition `xs` at temperature `T`. Return `{"P_bubble": float, "ys": list, "K_values": list}`.

**CLI**

`python3 /app/pr_flash.py input.json output.json`

Input JSON contains parameter keys. If key `"mode"` equals `"bubble"`, perform bubble-point calculation (requires `Tcs`, `Pcs`, `omegas`, `xs`, `T`). Otherwise perform PT flash (requires `Tcs`, `Pcs`, `omegas`, `zs`, `T`, `P`). Optional keys: `kijs`, `eos`.

**Tolerances vs. reference**

| Quantity | Tolerance |
|---|---|
| Compositions, fugacity coefficients | rel 1e-4 |
| V/F | abs 1e-4 |
| Departure enthalpy, entropy | rel 5e-3 |
| Bubble pressure | rel 1e-3 |
| K-values | rel 1e-4 |

Gas constant: R = 8.314462618 J/(mol·K). Iterate until max|delta ln K_i| < 1e-10 between successive substitution iterations.
