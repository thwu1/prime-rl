Build a CLI tool at `/app/dioptra_analyzer.py` that statically analyzes NIST Dioptra experiment YAML workflow definitions and outputs a JSON report to stdout. The tool takes a single YAML file path as its argument.

Dioptra experiments declare task plugins, a DAG of execution steps with parameter references and dependencies, and global parameters. The experiment schema is at `/app/schema/experiment_schema.json`. Five experiments of varying complexity are in `/app/experiments/`.

## Invocation Styles

Steps use three styles: **positional** (`step: {task: value_or_list}`), **keyword** (`step: {task: {param: value}}`), and **mixed** (`step: {task: name, args: [...], kwargs: {...}}`). Detect mixed style by the presence of a `task` key. Steps may include a `dependencies` field (string or list) for explicit ordering.

## Reference Resolution

`$name` references a global parameter or step (creating an implicit dependency). `$step.output_name` references a specific output. `$$escaped` is a literal, not a reference. Recursively scan nested dicts/lists in parameter values.

## Required Analysis

Construct the dependency DAG from both implicit (reference-based) and explicit edges. Detect cycles and report the cycle path. For acyclic graphs, compute: topological order (Kahn's algorithm, alphabetical tie-breaking), step depths (longest path from any root), critical path (longest path; ties broken by alphabetically first endpoint, tracing back via alphabetically first predecessor at target depth), and maximum parallelism (max steps at any depth level).

Detect issues: `unresolvable_reference` (no matching parameter/step/artifact), `undefined_task` (short name not in `tasks` section), `invalid_output_reference` (`$step.output` where output is not in the task's defined outputs), `unused_parameter` (defined but unreferenced), and `cycle`.

Track which global parameters are used vs unused.

## Output Format

```json
{
  "file": "<path>",
  "num_steps": 4,
  "num_edges": 4,
  "has_cycle": false,
  "cycle_path": null,
  "topological_order": ["step1", "step2", "step3", "step4"],
  "critical_path": ["step1", "step2", "step3", "step4"],
  "critical_path_cost": 4,
  "max_parallelism": 2,
  "step_depths": {"step1": 0, "step2": 1, "step3": 1, "step4": 2},
  "global_params_used": ["param_a", "param_b"],
  "unused_params": ["param_c"],
  "issues": [
    {"type": "unused_parameter", "severity": "warning", "parameter": "param_c", "message": "..."}
  ]
}
```

When `has_cycle` is true, set `topological_order`, `critical_path`, `critical_path_cost`, `max_parallelism`, and `step_depths` to `null`.

The tool must correctly analyze all five experiments in `/app/experiments/`.