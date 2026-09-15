A MODFLOW 6 groundwater flow model at `/app/model/` is intended to reproduce the TWRI benchmark (McDonald & Harbaugh, 1988): a 5-layer aquifer system with aquifers (layers 1, 3, 5) and confining units (layers 2, 4), discretized on a 15×15 grid with 5000 ft cell spacing. Units are feet and seconds. The model contains multiple defects that produce incorrect results or prevent convergence. No description of the errors is provided — diagnose and repair all defects using your knowledge of the TWRI problem, aquifer/confining-unit physics, and MODFLOW 6 input conventions.

Produce the following deliverables for the corrected baseline model (before adding new wells):

`/app/results/budget_analysis.json` — Volumetric water budget evaluation with keys: `total_inflow_ft3ps` (total inflow rate in ft³/s), `total_outflow_ft3ps` (total outflow rate in ft³/s), `percent_discrepancy` (budget closure error as percentage).

`/app/results/model_assessment.json` — Physical behavior assessment with keys: `max_head_layer1` (maximum computed head in layer 1), `max_head_layer5` (maximum computed head in layer 5), `head_at_center_l1` (head at layer 1, row 8, col 8), `head_at_center_l5` (head at layer 5, row 8, col 8), `vertical_gradient_positive` (boolean: head decreases with depth at domain center, consistent with downward flow from surface recharge), `drains_removing_water` (boolean: drains are actively discharging groundwater).

Then design a supplemental extraction well field. Add new wells beyond the existing 15 satisfying ALL constraints simultaneously:
- Total new extraction ≥ 20 ft³/s
- 3 to 8 new wells inclusive
- No single well rate exceeding 7 ft³/s in magnitude
- Wells placed only in aquifer layers (1, 3, or 5)
- At least 2 distinct aquifer layers must contain new wells
- The augmented simulation must converge normally
- No computed head in any cell may fall below that layer's bottom elevation

`/app/results/well_design.csv` — Columns: `layer,row,col,rate` listing only the new wells (negative rates for extraction).

`/app/results/heads.csv` — Full head distribution from the augmented simulation with columns: `layer,row,col,head` (1-indexed, all 1125 cells).