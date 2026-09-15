Build `/app/validate_plan.py` — a validator for NASA Astrobee `.fplan` flight plan files that checks them against the plan schema, hardware constraints, keepout zones, and arm safety rules.

## Provided Files

- `/app/schema/plan_schema.json` — xpjson 0.2 plan schema with `paramSpecs` (reusable parameter definitions by `id`) and `commandSpecs` (command definitions whose params may use `"parent"` references to inherit constraints from `paramSpecs`).
- `/app/config/hardware_limits.json` — Per-camera resolution/frame-rate limits and arm safety thresholds.
- `/app/zones/iss_keepout.json` — Keepout zones as axis-aligned bounding boxes.
- `/app/plans/*.fplan` — Flight plans to validate.

## Required Output

`python3 /app/validate_plan.py <fplan>` must print JSON to stdout:

```json
{
  "file": "<basename>",
  "valid": true|false,
  "violations": [{"type": "...", "severity": "error"|"warning", "message": "..."}],
  "summary": {"total_violations": N, "errors": N, "warnings": N}
}
```

Exit 0 if valid, non-zero otherwise.

## Violation Categories

1. **Unknown commands** — `type` not in schema `commandSpecs`.
2. **Parameter range violations** — Numeric values outside `minimum`/`maximum` from the resolved param spec (follow `parent` references to inherit from `paramSpecs`). Violation type: `range_violation`.
3. **Invalid enum values** — String values not in the resolved `choices` labels. Violation type: `invalid_enum`.
4. **Camera hardware incompatibility** — Resolution or frame rate unsupported by the specific camera per hardware limits. Types: `camera_resolution`, `camera_frame_rate`.
5. **Arm collision safety** — Pan must be 0 when tilt > 90 (type: `arm_collision_risk`). Gripper must be closed when tilt > 160 (type: `arm_gripper_collision`). Gripper open/closed state must be tracked across sequential commands at each station.
6. **Keepout zone violations** — Station coordinates inside any keepout AABB. Type: `keepout_zone`. Message must include the zone name.
7. **Inertia matrix symmetry** — `inertiaConfiguration.matrix` (3x3 as flat 9-element array) must be symmetric. Type: `inertia_symmetry`.