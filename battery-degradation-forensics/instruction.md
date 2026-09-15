A lithium-ion cell described by PyBaMM's `Chen2020` parameter set (LG M50, NMC/graphite, 5 Ah nominal) has been stored under conditions that consumed 0.135 A·h of cyclable lithium through SEI formation on the negative electrode.

Produce `/app/soh_analysis.py` that writes `/app/results.json` — a JSON object with exactly four top-level keys described below.

**`formation`** — The cell's degraded electrochemical state reflecting 0.135 A·h of lithium consumed by negative-electrode SEI:
`capacity_loss_ah`, `initial_stoichiometry`, `degraded_stoichiometry`, `sei_thickness_nm`, `degraded_porosity`

**`discharge`** — 1C-to-2.5 V discharge comparison, pristine cell vs. storage-degraded cell:
`pristine_capacity_ah`, `degraded_capacity_ah`, `capacity_difference_ah` (A·h); `pristine_energy_wh`, `degraded_energy_wh` (W·h)

**`degradation_trajectory`** — Two-stage aging assessment of the degraded cell under EC-reaction-limited SEI growth at kinetic rate constant 1×10⁻¹³ m/s. Each stage consists of 10 CCCV ageing cycles (discharge 1C to 3 V, 1 h rest, charge 1C to 4.2 V, CV hold to C/50), followed by a 1C reference-performance-test discharge to 2.5 V from a fully charged state. Stage 2 continues from the electrochemical state at the end of Stage 1's RPT:
`stage1_rpt_ah`, `stage2_rpt_ah`, `stage1_retention_pct`, `stage2_retention_pct` (RPT capacity as percentage of degraded discharge capacity), `stage1_sei_nm`, `stage2_sei_nm`, `capacity_fade_per_stage_pct` (percentage of Stage 1 RPT capacity lost by Stage 2)

**`sensitivity`** — Single-stage assessment (10 CCCV ageing cycles + RPT, same protocol as one stage above) repeated at SEI kinetic rate constants 1×10⁻¹⁴, 1×10⁻¹³, and 1×10⁻¹² m/s:
`retention_1e-14`, `retention_1e-13`, `retention_1e-12` (capacity retention %); `sei_growth_nm_1e-14`, `sei_growth_nm_1e-13`, `sei_growth_nm_1e-12` (net SEI thickness increase during cycling, nm)

**Success criteria:**

- All values are numeric floats, finite, non-NaN.
- `capacity_difference_ah` equals `pristine_capacity_ah` minus `degraded_capacity_ah`.
- Pristine capacity exceeds degraded capacity; Stage 1 RPT capacity is less than pristine.
- Energy-to-capacity ratios fall within the NMC/graphite operating voltage window.
- Stage 2 RPT ≤ Stage 1 RPT; Stage 2 SEI ≥ Stage 1 SEI ≥ formation SEI thickness.
- `capacity_fade_per_stage_pct` = (stage1_rpt − stage2_rpt) / stage1_rpt × 100.
- Higher SEI rate constants produce monotonically lower retention and higher SEI growth.
- `sensitivity.retention_1e-13` and `degradation_trajectory.stage1_retention_pct` are consistent (both represent 10-cycle results at k = 1×10⁻¹³).
- `sensitivity.sei_growth_nm_1e-13` matches Stage 1 SEI growth above formation thickness.
- The JSON contains exactly these four top-level keys with the field names specified above.
