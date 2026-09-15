Build a Python tool at `/app/planner.py` that analyzes Codemod workflow YAML files and produces a deterministic JSON execution plan.

Codemod workflows define a DAG of nodes with steps, matrix fan-out strategies, shared state, parameterized configuration, conditional step execution, and template expression interpolation. The JSON Schema for the workflow format is at `/app/schema.json`. Sample workflows are in `/app/workflows/`. Planner configuration is in `/app/planner_config.json` — the planner must read and apply all settings from this file.

## CLI Interface

    python3 /app/planner.py <workflow.yaml> [--param key=value ...]

## Output Format (JSON to stdout)

    {
      "plan_format_version": "string (from planner_config.json)",
      "valid": bool,
      "errors": ["..."],
      "execution_plan": [
        {
          "node_id": "string",
          "node_name": "string",
          "task_index": 0,
          "matrix_values": {},
          "steps": [
            {
              "name": "string",
              "type": "run|js-ast-grep|ast-grep|codemod|ai|shard|install-skill",
              "will_execute": true,
              "resolved_run": "string (only for run-type steps)"
            }
          ]
        }
      ],
      "final_state": {},
      "plan_digest": "string (first 16 hex chars of SHA-256)"
    }

## Semantics

- **Planner configuration**: Read `/app/planner_config.json` at startup. The `plan_format_version` field from the config must appear in every output JSON. The `digest_salt` is used for computing the `plan_digest`.
- **DAG ordering**: Nodes execute in topological order via `depends_on`. When multiple nodes are ready at the same topological level, tie-break using the `priority_weights` mapping from the planner config: look up each node ID in the map; IDs not found use the `_default` entry. Lower weight executes first. Equal weights use alphabetical node ID order.
- **Plan digest**: Computed as the first 16 hex characters of SHA-256(`digest_salt` concatenated with a pipe-separated list of `node_id:task_index` entries from the execution plan in order). For invalid workflows with empty execution plans, compute over the salt alone.
- **Cycle detection**: Cyclic dependencies are validation errors.
- **Reference validation**: `depends_on` entries referencing nonexistent node IDs are errors.
- **Matrix expansion**: Nodes with `strategy.type: matrix` fan out into one task per entry in `strategy.values` (inline) or `strategy.from_state` (dynamic, reading from current workflow state). Tasks ordered by array position.
- **State tracking**: Initialized from `state.schema` (list and dict syntax). In `run` steps, `KEY=VALUE` lines set state; `KEY@=VALUE` appends to arrays. Values parsed as JSON when valid. Mutations only apply when `will_execute` is true.
- **Parameters**: Resolved from `params.schema` defaults, overridden by `--param` CLI args. Types: `string`, `boolean` (`true/false/yes/no/1/0`), `number`.
- **Expression resolution**: `${{ params.x }}`, `${{ state.x }}`, `${{ matrix.x }}` templates in `run` commands are replaced with resolved values. Booleans render as lowercase `true`/`false`.
- **Condition evaluation**: Step `if` expressions support variable references (`params.x`, `state.x`, `matrix.x`), comparison operators (`==`, `!=`, `>`, `<`, `>=`, `<=`), and logical operators (`&&`, `||`). Unquoted `true`/`false` are boolean; quoted values are strings; numeric literals are numbers.
- **Step types**: Determined by which key is present (`run`, `js-ast-grep`, `ast-grep`, `codemod`, `ai`, `shard`, `install-skill`). Only `run` steps produce `resolved_run`.
- **Invalid workflows**: Return `valid: false` with descriptive errors, empty `execution_plan`, empty `final_state`. Still include `plan_format_version` and compute `plan_digest` normally.