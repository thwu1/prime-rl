A MASSim "Agents Assemble" game engine at `/app/engine.py` (~780 lines) simulates a multi-agent grid-world on a torus with 12 action types, attachment-graph physics, role-based permissions, energy management, norm enforcement, and cooperative task submission. The engine's behavior diverges from a verified reference implementation in multiple ways.

The specification documents at `/app/docs/` are deliberately incomplete — critical mechanics including rotation transform directions, deadline boundary conditions, attachment edge properties, energy recharge eligibility, and norm enforcement ordering are not fully defined in the written docs. Correct behavior for these mechanics must be determined empirically from the reference data.

## Deliverables

**1. Corrected engine** — Evaluate `/app/engine.py` against the reference data, determine the correct semantics for each ambiguous mechanic, and fix all behavioral divergences.

**2. Behavioral specification** — Create `/app/behavioral_spec.json` that formally documents the correct semantics you determined for each ambiguous area. Use this structure:

```json
{
  "rotation": {
    "cw_south_block_direction": "<cardinal direction a south block moves on CW rotation>",
    "ccw_south_block_direction": "<cardinal direction a south block moves on CCW rotation>"
  },
  "task_deadline": {
    "submit_at_exact_deadline_step": "<allowed or rejected>"
  },
  "connect_action": {
    "edge_directionality": "<unidirectional or bidirectional>"
  },
  "energy_lifecycle": {
    "recharge_while_deactivated": <true or false>,
    "reactivation_energy_source": "<config parameter name>"
  },
  "norm_enforcement": {
    "order": "<penalty_then_deactivation_check or deactivation_check_then_penalty>"
  },
  "action_dispatch": {
    "unknown_action_result_code": "<result code string>"
  }
}
```

## Reference data

- `/app/replays/*.json` — Seven reference behavior traces
- `/app/reference.db` — SQLite database with reference action results, agent states, block positions, and scores
- `/app/logs/server.ndjson` — Structured event logs from the reference implementation
- `/app/docs/scenario.md` — Partial game mechanics specification
- `/app/docs/api_spec.md` — Engine API contract and action processing order
- `/app/Makefile` — Analysis orchestration targets
- `/app/tools/trace_diff.py` — Trace comparison utility
- `/app/filters/*.jq` — Predefined jq filters for log analysis