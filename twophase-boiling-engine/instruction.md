Create a Python CLI tool at `/app/twophase.py` that performs two-phase flow boiling analysis for engineering applications.

When executed as `python3 /app/twophase.py`, the tool must read operating conditions from `/app/conditions.json` and write computed results to `/app/results.json`.

**Input** (`/app/conditions.json`): A JSON array of case objects. Each has `id` (string), `type` (string), optionally `method` (string), and `params` (object with SI-unit values).

**Output** (`/app/results.json`): A JSON object mapping each case `id` to its result object.

**Case types and required correlations:**

*`pressure_drop`* — return `{"dP": <Pa>}`. Methods:
- `Friedel` (1979): two-phase multiplier approach using liquid-only pressure drop, homogeneous void fraction for Froude/Weber numbers. Params: `m, x, rhol, rhog, mul, mug, sigma, D, roughness, L`.
- `Gronnerud` (1972): liquid Froude number based correction with special handling when Fr_l >= 1. Params: `m, x, rhol, rhog, mul, mug, D, roughness, L`.
- `Chisholm` (1973): Gamma-based method with B coefficient depending on mass flux G and Gamma ranges (<9.5, 9.5-28, >28). Blasius exponent n=0.25. Params: `m, x, rhol, rhog, mul, mug, D, roughness, L`.

*`void_fraction`* — return `{"homogeneous": <val>, "thom": <val>, "xtt": <val>}`. Params: `x, rhol, rhog, mul, mug`. Compute homogeneous void fraction, Thom (1964) slip-ratio model, and Lockhart-Martinelli Xtt parameter.

*`flow_boiling`* — return `{"h": <W/m²/K>}`. Method `Chen_Bennett`: combines Dittus-Boelter convective term (Nu=0.023·Re_l^0.8·Pr_l^0.4) with Forster-Zuber nucleate boiling, using enhancement factor F and suppression factor S from Bennett's formulation involving Xtt and a characteristic bubble length X0. Params: `m, x, D, rhol, rhog, mul, mug, kl, Cpl, Hvap, sigma, dPsat, Te`.

*`pool_boiling`* — return `{"h": <W/m²/K>}`. Method `Gorenflo`: VDI Heat Atlas corresponding-states method with CAS-indexed reference heat transfer coefficients h0 from the 1993 table (44 fluids). Has separate formulations for water vs other fluids. Reference conditions: q0=20000 W/m², Ra0=0.4 µm. Params: `P, Pc, q, cas`.

**Friction factor**: All pressure drop correlations need the Darcy friction factor. Use the Colebrook equation (exact or iterative). For Re < 2040, use f=64/Re. g=9.80665 m/s².

**Precision**: Pressure drops within 1% of reference values. Heat transfer coefficients within 0.5%. Void fractions within 0.01%.
