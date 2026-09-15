Water analyses for three sources are provided in `/app/sources.json`. Blending scenarios with mixing fractions are in `/app/scenarios.json`.

Using the PHREEQC 3 geochemical modeling engine (source: `https://github.com/phreeqc-dev/phreeqc3`) with its bundled `phreeqc.dat` thermodynamic database, produce `/app/results.json` containing computed water quality parameters for each scenario at each evaluation temperature listed in `scenarios.json`.

For each scenario, sources are mixed according to the given mass fractions (summing to 1.0), then the blended water is evaluated at each temperature. Compute:

- **pH**: equilibrium pH of the blended water at the evaluation temperature.
- **calcite_si**: saturation index of calcite.
- **ccpp_closed_mmol_per_kgw**: calcium carbonate precipitation potential in a closed system (no gas exchange), in mmol per kg water. Positive = net precipitation (scaling); negative = net dissolution (aggressive water).
- **ccpp_open_mmol_per_kgw**: CCPP in a system open to atmospheric CO2 at log partial pressure −3.5, in mmol per kg water. Same sign convention.

Data notes: alkalinity values in the source data are mg/L as CaCO3. Chloride serves as the charge-balance ion for each source solution.

Required output schema (`/app/results.json`):
```json
{
  "scenarios": [
    {
      "scenario_id": "<name>",
      "results_by_temperature": {
        "5.0": {
          "pH": <float>,
          "calcite_si": <float>,
          "ccpp_closed_mmol_per_kgw": <float>,
          "ccpp_open_mmol_per_kgw": <float>
        },
        "15.0": { "..." : "..." },
        "25.0": { "..." : "..." }
      }
    }
  ]
}
```

Scenarios must appear in the same order as in `scenarios.json`. Temperature keys are the string representation of the float (e.g. `"5.0"`).

Numerical tolerances: pH ±0.02, calcite_si ±0.05, CCPP ±0.02 mmol/kgw or 5% relative (whichever is larger).
