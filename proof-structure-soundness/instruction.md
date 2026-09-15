A formal verification team has exported their JasperGold proof plan for an SoC design. The proof hierarchy — including decomposition strategies, assumption/guarantee bindings, and proof obligations — is defined in `/app/proof_plan.tcl` using JasperGold proof plan conventions. Case-split conditions are specified as SMT-LIB2 constraint definitions in `/app/constraints/`. Signal domain definitions and value encodings are in `/app/design_spec.json`.

Audit this proof structure for soundness and produce `/app/audit_report.json` conforming to the following schema:

```json
{
  "overall_sound": <bool>,
  "circular_dependencies": [
    {"cycle": ["<sorted node IDs>", ...]}
  ],
  "incomplete_case_splits": [
    {"node_id": "<id>", "signal": "<signal>", "covered": ["<sorted>"], "missing": ["<sorted>"]}
  ],
  "decomposition_soundness": {
    "<non-leaf node_id>": <bool>
  }
}
```

`covered` and `missing` values must use human-readable signal value names from `design_spec.json`, not numeric encodings. All lists must be sorted. `decomposition_soundness` must include every non-leaf node in the hierarchy.