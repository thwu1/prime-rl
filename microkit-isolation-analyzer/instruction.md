The isolation analysis tool at `/app/analyzer.py` evaluates security properties of a mixed-criticality seL4 Microkit system for DO-178C/DO-326A certification. When executed, it analyzes the system description at `/app/system.xml` against the security policy at `/app/policy.json` and writes results to `/app/report.json`.

The tool's output has failed certification review. The formal specification defining the correct analysis semantics is at `/app/osmosis_spec.md`. A third-party certification audit report produced through black-box output comparison is at `/app/certification_report.md`.

Fix the analyzer so that it produces results conforming to the OSmosis specification, then generate the following additional outputs:

- `/app/report.json` — Corrected isolation analysis (same JSON schema the tool already uses).
- `/app/dependency_graph.dot` — Graphviz DOT digraph of the corrected direct dependency graph, with quoted node names and one edge per line.
- `/app/dependency_graph.svg` — The DOT graph rendered to SVG via the `dot` command-line tool.
- `/app/critical_paths.json` — For each isolation policy violation in the corrected analysis, the shortest dependency chain demonstrating transitive reachability:

```json
{
  "isolation_violation_paths": [
    {
      "pair": ["<pd_a>", "<pd_b>"],
      "path": ["<dependent_pd>", "<intermediate>", "...", "<target_pd>"]
    }
  ]
}
```

Each path traces dependency edges from the PD whose TCB contains the violating PD to that violating PD. Entries sorted alphabetically by violation pair.