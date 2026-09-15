Build `/app/analyze.py`, a CLI tool for binary gas adsorption mixture thermodynamics using raw isotherm data in `/app/data/`.

**Isotherm JSON format:** Each file contains `isotherm_data` (array of `{"pressure": float, "loading": float}` objects), `temperature` (K), `material`, `pressure_mode` ("absolute"), `pressure_unit` ("bar"), `loading_basis` ("molar"), `loading_unit` ("mmol"), `material_unit` ("g").

**Subcommands:**

`python3 /app/analyze.py iast <iso1> <iso2> <y1> <y2> <P_total>`

Predict binary mixture adsorption equilibrium using Ideal Adsorbed Solution Theory. Arguments: two single-component isotherm file paths, gas-phase mole fractions (y1, y2), total pressure (bar). Write JSON to stdout:

```json
{"adsorbed_fractions": [x1, x2], "selectivity": S12}
```

`x_i` are adsorbed-phase mole fractions. `selectivity` = (x1/y1)/(x2/y2).

`python3 /app/analyze.py enthalpy <iso1> <iso2> [<iso3> ...]`

Compute isosteric enthalpy of adsorption from isotherms at different temperatures on the same material via the Clausius-Clapeyron approach. Use 50 equally-spaced loading points spanning the common loading range (1.01x maximum of per-isotherm minima to 0.99x minimum of per-isotherm maxima). Write JSON to stdout:

```json
{"loading": [...], "isosteric_enthalpy": [...], "average_enthalpy": <float>}
```

`loading` in mmol/g, `isosteric_enthalpy` in kJ/mol (array), `average_enthalpy` is the arithmetic mean.

`python3 /app/analyze.py svp <iso1> <iso2> <y1> <y2> <P_min> <P_max> <N>`

Compute IAST selectivity vs total pressure. Arguments: isotherm paths, gas-phase mole fractions, pressure range (bar), number of linearly-spaced pressure points. Write JSON to stdout:

```json
{"pressures": [...], "selectivities": [...], "mean_selectivity": <float>}
```

**Accuracy requirements:**
- IAST adsorbed fractions at equimolar feed, 1 bar: absolute error < 0.015 (reference: x_CH4 ~ 0.188, x_C2H6 ~ 0.812)
- IAST selectivity at equimolar feed, 1 bar: absolute error < 0.05 (reference: ~ 0.232)
- Isosteric enthalpy average: absolute error < 2.0 kJ/mol (reference: ~ 28.0 kJ/mol)
- SVP mean selectivity over [0.01, 10] bar (30 points), equimolar feed: absolute error < 0.05 (reference: ~ 0.19)

**Data files in `/app/data/`:**
- `ch4_mof5.json` -- methane on MOF-5(Zn), 298 K
- `c2h6_mof5.json` -- ethane on MOF-5(Zn), 298 K
- `butane_298K.json` -- n-butane on activated carbon, 298.15 K
- `butane_323K.json` -- n-butane on activated carbon, 323.15 K
- `butane_348K.json` -- n-butane on activated carbon, 348.15 K

**Constraints:** No adsorption-specific libraries (pyGAPS, pyIAST). General scientific computing libraries (numpy, scipy) are permitted.
