Create `/app/cascade.py` — a general N-stage cascade refrigeration system analyzer.

Plant specifications are at `/app/plants/*.json`. Field measurement data is at `/app/commissioning/plant_a_field.json`.

**Plant spec schema**:
```json
{
  "name": "string",
  "stages": [{
    "id": "string",
    "refrigerant": "CoolProp fluid name",
    "compressor": {"isentropic_efficiency": float},
    "evaporator": {"saturation_temperature_K": float, "superheat_K": float},
    "condenser": {"saturation_temperature_K": float, "subcool_K": float}
  }],
  "cascade_heat_exchangers": [
    {"hot_stage": "string", "cold_stage": "string", "approach_temperature_K": float}
  ],
  "cascade_temperatures_K": [float, ...],
  "cooling_capacity_W": float
}
```

Stages are ordered from lowest to highest operating temperature. Only the lowest stage specifies `evaporator.saturation_temperature_K`; only the highest specifies `condenser.saturation_temperature_K`. Each cascade heat exchanger couples two stages: the hot stage condenses at `T_cascade + approach/2` and the cold stage evaporates at `T_cascade - approach/2`.

**CLI** (JSON to stdout):

`python3 /app/cascade.py analyze <plant.json>` — Per-stage results keyed by stage ID: `COP`, `w_comp` (J/kg), `q_evap` (J/kg), `q_cond` (J/kg), `T_discharge_K`, `pressure_ratio`, `mass_flow_kg_s`, `states` (list of 4 dicts with `T`, `P`, `H`, `S` for compressor inlet, compressor outlet, condenser outlet, expansion valve outlet). System-level: `system_COP`, `total_power_W`, `stages` (dict), `cascade_hx_duties_W` (list).

`python3 /app/cascade.py optimize <plant.json>` — Find cascade temperatures maximizing system COP to within 0.01 K. Output: `optimal_cascade_temperatures_K` (list), `maximum_COP`, `system` (full analysis at optimum).

`python3 /app/cascade.py diagnose <plant.json> <measured.json>` — Given `{"measured_discharge_temperatures_K": {"stage_id": float}}`, determine each compressor's actual isentropic efficiency from its measured discharge conditions and the design operating pressures. Output: `actual_efficiencies` (dict of stage ID to float), `efficiency_deviations` (dict of stage ID to actual minus design).

**Plants provided**: `plant_a.json` (2-stage R23/R134a), `plant_b.json` (3-stage Ethane/R23/Ammonia), `plant_c.json` (2-stage R23/R410A with near-critical high-side condensing at 333.15 K, where R410A T_critical is approximately 344.5 K).

**Requirements**: All thermodynamic quantities within 0.01% relative tolerance. Energy conservation must hold at every stage and cascade heat exchanger. Optimization must find the global maximum within the feasible cascade temperature range. Must handle near-critical condensing conditions correctly.
