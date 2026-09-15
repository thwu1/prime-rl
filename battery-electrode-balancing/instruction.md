The file `/app/cell_config.json` specifies a lithium-ion cell configuration: a base electrochemical parameter set, negative electrode thickness scaling factors to evaluate, discharge conditions, and a stoichiometry-based safety margin for lithium plating assessment.

Using the PyBaMM battery modeling framework (pre-installed), evaluate how varying the negative electrode thickness affects discharge performance and lithium plating safety for the specified cell chemistry. For each thickness multiplier in the configuration, simulate a full discharge and extract relevant electrochemical metrics.

Write all results to `/app/results.json` with this structure:

- `base_parameters`: object with `negative_electrode_thickness_m`, `positive_electrode_thickness_m`, `nominal_cell_capacity_Ah` (floats from the unmodified base parameter set)
- `analyses`: array of objects ordered by thickness multiplier, each containing:
  - `thickness_multiplier` (float)
  - `discharge_capacity_Ah` (float)
  - `discharge_energy_Wh` (float)
  - `average_voltage_V` (float)
  - `neg_stoich_at_soc100` (float): negative electrode stoichiometry at full charge
  - `neg_stoich_at_soc0` (float): negative electrode stoichiometry at end of discharge
  - `pos_stoich_at_soc100` (float): positive electrode stoichiometry at full charge
  - `pos_stoich_at_soc0` (float): positive electrode stoichiometry at end of discharge
  - `plating_risk` (boolean): whether this configuration presents lithium plating risk, assessed using the safety margin from the config
  - `limiting_electrode` (string: `"positive"` or `"negative"`): which electrode limits the cell's discharge capacity
- `optimal_multiplier`: float — the best-performing thickness multiplier among safe configurations, or null if all configurations have plating risk
- `max_safe_discharge_capacity_Ah`: float — discharge capacity at the optimal configuration, or 0.0 if no safe configuration exists