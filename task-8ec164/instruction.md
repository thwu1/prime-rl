Six `.sysml` files in `/app/model/` define a lunar cargo delivery spacecraft in SysML v2 textual notation. The model includes type definitions, a hierarchical system architecture with quantitative attributes, formal requirements with constraint semantics, calculation definitions (including the Tsiolkovsky rocket equation), satisfaction/derivation relationships, and a mission context specifying the staging sequence. Some parts carry design-margin attributes (e.g. `designMass`, `allocatedMass`, peak power values) that must be distinguished from the actual engineering values used in analysis.

Parse the model and produce three artifacts:

### `/app/selene_model.db`

SQLite database with the part hierarchy, attributes, requirements, and traceability in normalized form:

- `parts` (`id` INTEGER PK, `name` TEXT, `parent_id` INTEGER nullable FK→parts, `type_name` TEXT nullable)
- `attributes` (`id` INTEGER PK, `part_id` INTEGER FK→parts, `attr_name` TEXT, `attr_value` REAL) — booleans as 0.0/1.0
- `requirements` (`id` INTEGER PK, `req_id` TEXT, `name` TEXT, `type_name` TEXT)
- `req_attributes` (`id` INTEGER PK, `requirement_id` INTEGER FK→requirements, `attr_name` TEXT, `attr_value` REAL)
- `satisfy_links` (`id` INTEGER PK, `req_name` TEXT, `target_path` TEXT)
- `derive_links` (`id` INTEGER PK, `child_req_name` TEXT, `parent_req_name` TEXT)

Only `part` usages inside `seleneSystem` go into the database (not `part def`, `port`, `connection`, `interface`, `state`, `action`, `use case`, or other SysML v2 element kinds).

### `/app/analysis_report.json`

JSON with these keys:

- **`mass_rollup`**: Recursive mass budget rooted at `"seleneSystem"`. Each node: `"mass"` (float) and optional `"children"` dict. Composite mass = sum of children; leaf mass = `mass` attribute. Ignore `designMass`/`allocatedMass`/`contingencyMass`.
- **`delta_v_budget`**: Per-vehicle entries (`"transferVehicle"`, `"lander"`) with `"specificImpulse"`, `"initialMass"`, `"finalMass"`, `"deltaV"`. Also `"totalDeltaV"`. Apply staging from MissionContext: TV initial mass = full stack; lander initial mass = lander only. Final mass = initial minus consumable propellant (`isConsumable=true`). Use `deltaV = Isp * g0 * ln(m_i / m_f)`, `g0 = 9.80665`.
- **`power_budget`**: Per-vehicle: `"generation"` (sum of `powerGeneration`), `"consumption"` (sum of `powerConsumption`), `"margin"` (difference). Exclude peak/transient attributes.
- **`requirements_verification`**: Keyed by requirement ID. Each: `"status"` (`"PASS"`/`"FAIL"`), `"actual"` (float), `"limit"` (float). Evaluate constraint direction from requirement type definitions.
- **`traceability`**: Keyed by requirement ID. `"satisfiedBy"`: list of component names (last segment of satisfy target path). Empty list = traceability gap.
- **`derivation_chains`**: Maps derived requirement names to lists of parent requirement names (from `derive requirement` inside requirement specialization blocks).

### `/app/traceability.dot`

Graphviz DOT digraph: requirements and components as distinct node shapes, edges from satisfy relationships, visually distinguish PASS/FAIL, mark traceability gaps.