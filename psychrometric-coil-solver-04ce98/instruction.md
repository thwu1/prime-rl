The program `/app/psychro_calc` computes moist air psychrometric properties and HVAC cooling coil processes per ASHRAE Handbook - Fundamentals (2017) Chapter 1, SI units. It reads commands from stdin and writes results to stdout.

**Commands** (one per line, space-separated values):

- `SATVP <tdb>` — saturation vapor pressure (Pa)
- `SATW <tdb> <pressure>` — saturated humidity ratio (kg/kg)
- `W_WB <tdb> <twb> <pressure>` — humidity ratio from wet-bulb
- `WB_W <tdb> <w> <pressure>` — wet-bulb from humidity ratio
- `ENTHALPY <tdb> <w>` — moist air enthalpy (J/kg)
- `VOLUME <tdb> <w> <pressure>` — specific volume (m^3/kg)
- `DENSITY <tdb> <w> <pressure>` — density (kg/m^3)
- `STATE_WB <tdb> <twb> <p>` — full state: `W Tdp Twb RH VapPres h v density`
- `STATE_DP <tdb> <tdp> <p>` — full state: `W Tdp Twb RH VapPres h v density`
- `STATE_RH <tdb> <rh> <p>` — full state: `W Tdp Twb RH VapPres h v density`
- `COIL <oa_tdb> <oa_twb> <ra_tdb> <ra_rh> <oa_frac> <bf> <target_tdb> <airflow_kgs> <pressure>` — outputs: `mixed_tdb mixed_w adp leaving_tdb leaving_w q_total_kw q_sensible_kw q_latent_kw`

**Starting state**: `/app/` contains C source files and a `Makefile`. Run `make` to build `psychro_calc`. The psychrometric library `psychro.c` contains multiple bugs in its implementation of the ASHRAE equations. The HVAC process module `ahu.c` has stub implementations that return zeros.

**Requirements**:

1. Fix all bugs in `/app/psychro.c` so that psychrometric calculations match ASHRAE Handbook 2017 Ch. 1 reference values. Saturation vapor pressure must agree with Table 3 within 300 ppm. Iterative solvers (wet-bulb bisection, dew-point Newton-Raphson) must converge to within 0.001 C. The humidity ratio equations (eqn 33/35) must use the correct coefficients for both above-freezing and below-freezing wet-bulb temperatures.

2. Implement the HVAC process functions in `/app/ahu.c`: mixed air state (mass-weighted average of humidity ratio and enthalpy, dry-bulb derived from the inverse enthalpy equation), apparatus dew point from bypass factor relationship, coil leaving state using the bypass factor model with saturation at the ADP, and sensible/latent/total cooling loads from air state differences and mass flow rate.

3. `make` in `/app/` must produce the executable `/app/psychro_calc` without errors.
