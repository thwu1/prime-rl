A PHREEQC reactive transport model at `/app/drain_model.pqi` was developed to simulate performance of an anoxic limestone drain treating acid mine drainage. PHREEQC Version 3 source code is at `/app/phreeqc3_src/`, and field observations from the operating drain are at `/app/field_observations.json`.

The model contains multiple errors across its geochemical and transport configuration. When run, it produces results that are physically unreasonable and inconsistent with the field measurements. All errors must be identified and corrected to bring the model into agreement with the observations.

Produce a corrected model at `/app/corrected_model.pqi` whose selected output is written to `/app/transport_results.tsv`, and write the corrected simulation's predictions to `/app/results.json`:

```json
{
  "effluent_pH": <number>,
  "effluent_Ca_mol_kgw": <number>,
  "effluent_SO4_mol_kgw": <number>,
  "calcite_remaining_cell1": <number>,
  "gypsum_si_cell10": <number>
}
```

All values must be numeric and extracted from the final transport shift. "Effluent" is cell 10 (drain outlet); "cell 1" is the drain inlet. Use the `phreeqc.dat` thermodynamic database from the source distribution.