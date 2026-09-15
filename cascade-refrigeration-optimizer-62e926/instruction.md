The `/app/data/` directory contains design and operational data for a cascade refrigeration facility evaluating three candidate system configurations. Create `/app/audit.py` that reads all relevant data, performs a comprehensive thermodynamic performance audit, and writes results to `/app/audit_results.json`.

Explore `/app/data/` to discover and cross-reference system definitions, equipment specifications, site conditions, environmental parameters, and refrigerant inventory records.

For each system, the audit must determine:

**Design-point performance** at the nominal ambient condition: find the cascade temperature that maximizes overall system COP within thermodynamically feasible limits. Report COP, Carnot COP, second-law efficiency, per-circuit and total compressor power, total exergy destruction, and identify the component with the largest exergy destruction contribution.

**Seasonal performance** across the provided ambient temperature profile: at each ambient bin, optimize the cascade temperature and compute COP. Report properly-weighted seasonal COP and annual energy consumption in kWh.

**TEWI** (Total Equivalent Warming Impact): compute direct and indirect contributions using the environmental and inventory data provided.

Identify which system achieves the best seasonal COP and which has the lowest TEWI.

Output schema (`/app/audit_results.json`):
```json
{
  "systems": [
    {
      "system_id": "<str>", "ltc_fluid": "<str>", "htc_fluid": "<str>",
      "design_point": {
        "T_cond_C": 0.0, "optimal_cascade_T_C": 0.0,
        "COP": 0.0, "carnot_COP": 0.0, "second_law_efficiency": 0.0,
        "W_total_kW": 0.0, "W_ltc_kW": 0.0, "W_htc_kW": 0.0,
        "exergy_destruction_total_kW": 0.0,
        "dominant_irreversibility": "<component>"
      },
      "seasonal": {
        "COP": 0.0, "annual_energy_kWh": 0.0,
        "per_bin": [{"T_ambient_C": 0.0, "COP": 0.0, "optimal_cascade_T_C": 0.0}]
      },
      "TEWI": {"direct_kg_CO2": 0.0, "indirect_kg_CO2": 0.0, "total_kg_CO2": 0.0}
    }
  ],
  "best_seasonal_COP": "<system_id>",
  "lowest_TEWI": "<system_id>"
}
```

Valid `dominant_irreversibility` values: `compressor_ltc`, `compressor_htc`, `condenser`, `evaporator`, `expansion_valve_ltc`, `expansion_valve_htc`, `cascade_hx`.

Run: `python3 /app/audit.py`
