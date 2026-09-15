A game engine at `/app/engine.py` implements a single-step resolver for Lux AI Season 3 matches. It was ported from the official JAX engine but produces incorrect state transitions. Ground-truth transitions from two matches are in `/app/replays/match_A.json` and `/app/replays/match_B.json` (compact field names — see the `note` field in each file). The partial specification at `/app/mechanics_reference.md` is deliberately incomplete: several behavioral details are left ambiguous and must be determined empirically from replay evidence.

Produce these deliverables:

**`/app/replay_analysis.db`** — A SQLite database populated from both replay files containing:
- Table `transitions`: columns `match_id TEXT`, `transition_id INTEGER`, `label TEXT`, `unit_count INTEGER`
- Table `unit_actions`: columns `match_id TEXT`, `transition_id INTEGER`, `team INTEGER`, `unit_id INTEGER`, `direction INTEGER`, `sap_dx INTEGER`, `sap_dy INTEGER`, `energy_before INTEGER`, `energy_after INTEGER`, `x_before INTEGER`, `y_before INTEGER`, `x_after INTEGER`, `y_after INTEGER`, `alive_after INTEGER`
- View `sap_events`: rows from `unit_actions` filtered to `direction = 5`
- View `energy_deltas`: all `unit_actions` columns plus a computed `energy_delta` column (`energy_after - energy_before`)

**`/app/spec_clarifications.json`** — Resolve each ambiguity in the specification by analyzing replay evidence. For each key below, determine which candidate is the correct engine behavior:
- `void_energy_snapshot`: which energy values does void field computation use? Candidates: `"pre_movement"`, `"post_movement_pre_sap"`, `"post_sap"`
- `collision_tie_behavior`: what happens when both teams have equal aggregate energy on a tile? Candidates: `"lower_team_removed"`, `"higher_team_removed"`, `"all_removed"`
- `sap_dropoff_rounding`: how is fractional AoE splash damage converted to integer? Candidates: `"floor"`, `"round"`, `"ceil"`
- `void_stacking_division`: when multiple friendly units share a tile, how is incoming void drain distributed? Candidates: `"no_division"`, `"divide_by_friendly_count"`

Format each entry as `{"candidates": [...], "determination": "<chosen>"}`.

**`/app/engine.py`** — Corrected engine that matches ground-truth behavior for all replay transitions.

**`/app/extracted_params.json`** — Hidden game parameters reverse-engineered from each match:
```json
{
  "match_A": {"unit_move_cost": 0, "unit_sap_cost": 0, "unit_sap_range": 0, "unit_sap_dropoff_factor": 0.0, "unit_energy_void_factor": 0.0, "nebula_tile_energy_reduction": 0, "max_unit_energy": 0},
  "match_B": {"...": "..."}
}
```

The `luxai-s3` Python package contains the authoritative JAX implementation if you need a reference beyond the replays.