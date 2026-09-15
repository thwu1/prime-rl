A C shared library and Python ctypes wrapper at `/app/` implement IAPWS-IF97 steam thermodynamic property calculations. The C source (`/app/src/if97_core.c`) implements forward property equations for Regions 1–5 and saturation curves. The Python wrapper (`/app/wrapper.py`) provides ctypes bindings, backward T(p,h) equations, and transport property stubs.

The implementation was ported from a reference codebase but contains multiple computational errors across both the C source and the Python wrapper that produce incorrect thermodynamic property values. Published IAPWS-IF97 computer-program verification values are at `/app/specs/iapws_verification.txt`.

**Required deliverables:**

1. A corrected, working shared library at `/app/libif97.so` (built via `make` in `/app/`)
2. A corrected `/app/wrapper.py` with all computational errors fixed
3. Viscosity (IAPWS 2008, μ₀·μ₁ only, no critical enhancement) and thermal conductivity (IAPWS 2011, λ₀·λ₁ only, λ₂=0) implemented as `IF97Engine.viscosity(rho, T)` returning Pa·s and `IF97Engine.thermal_conductivity(rho, T)` returning W/(m·K) in `/app/wrapper.py`
4. `/app/results.json` containing a Rankine cycle analysis per `/app/cycle_config.toml`

**`results.json` structure:**
```json
{
  "turbine_inlet": {"T": float, "p": float, "h": float, "s": float},
  "turbine_outlet_actual": {"h": float},
  "condenser_outlet": {"T": float, "p": float, "h": float, "s": float, "v": float},
  "pump_outlet": {"h": float},
  "cycle_efficiency": float,
  "net_specific_work_kj_per_kg": float,
  "heat_input_kj_per_kg": float,
  "back_work_ratio": float,
  "turbine_inlet_viscosity_pa_s": float,
  "turbine_inlet_conductivity_w_per_m_k": float
}
```

Units: T in K, p in MPa, h in kJ/kg, s in kJ/(kg·K), v in m³/kg.

All forward thermodynamic properties must match IAPWS-IF97 verification values to 1×10⁻⁶ relative tolerance. Transport properties must match IAPWS 2008/2011 verification values (without critical enhancement) to the same tolerance.
