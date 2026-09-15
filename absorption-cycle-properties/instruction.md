`/app/nh3h2o.py` implements the Patek-Klomfar (1995) polynomial correlations for ammonia-water mixture thermodynamic properties. It provides five correlation functions (all using MPa, K, kJ/kg, molar fractions of NH3):

- `T_from_px(p, x)` — bubble-point temperature
- `T_from_py(p, y)` — dew-point temperature
- `y_from_px(p, x)` — equilibrium vapor composition
- `Hl_from_Tx(T, x)` — saturated liquid enthalpy
- `Hg_from_Ty(T, y)` — saturated vapor enthalpy

plus `molar_to_mass(q)` and `mass_to_molar(q)` converters (M_NH3=17.031, M_H2O=18.015 g/mol).

The implementation contains errors causing incorrect outputs. Reference data for all five correlations is in `/app/benchmark_data.json`.

**Deliverables:**

1. **Fix `/app/nh3h2o.py`** so all five correlations match the reference data within ±0.01 K (temperatures), ±0.05 kJ/kg (enthalpies), ±1e-4 (vapor composition). Preserve existing function signatures.

2. **Add inverse functions** to `/app/nh3h2o.py`:
   - `p_from_Tx(T, x)` — bubble-point pressure [MPa] given temperature [K] and liquid molar fraction
   - `x_from_pT(p, T)` — liquid molar fraction given pressure [MPa] and temperature [K]
   - `T_from_hx(h, x)` — temperature [K] given liquid enthalpy [kJ/kg] and liquid molar fraction; must handle the non-monotonic behavior of `Hl_from_Tx` at high ammonia fractions; valid for T in [250, 450] K and x in [0, 0.65]

3. **Write `/app/cycle_results.json`** for the single-effect NH3-H2O absorption cycle with solution heat exchanger (SHX), as specified in `/app/cycle_spec.json`. The output JSON must contain these keys:

   `T_generator_K`, `T_absorber_K`, `y_refrigerant_molar`, `h_weak_gen_kJperkg`, `h_strong_abs_kJperkg`, `h_refrigerant_vapor_kJperkg`, `T_condenser_K`, `h_condensed_liquid_kJperkg`, `T_evaporator_K`, `h_evaporator_vapor_kJperkg`, `circulation_ratio`, `T_weak_SHX_out_K`, `h_strong_SHX_out_kJperkg`, `T_strong_SHX_out_K`, `Q_SHX_kW`, `Q_generator_kW`, `Q_evaporator_kW`, `COP_cooling`, `COP_no_SHX`

   The circulation ratio is mass-based (ṁ_strong / ṁ_refrigerant). Heat duties are in kW for the given mass flow rate. `COP_cooling` uses the SHX-modified generator duty; `COP_no_SHX` uses the generator duty without heat recovery. All state-point enthalpies must use the polynomial correlations — do not assume constant specific heat.
