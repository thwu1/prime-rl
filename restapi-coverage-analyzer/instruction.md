Three automated black-box testing tools were evaluated against a project management REST API. Produce a competition report integrating the evaluation artifacts at `/app/`:

- `api_spec.yaml` — OpenAPI 3.0 specification
- `traffic/*.jsonl` — Per-tool HTTP traffic captures (JSON lines with fields: `timestamp`, `method`, `path`, `status`, `request_headers`, `request_body`, `response_body`)
- `coverage/*.xml` — Per-tool JaCoCo XML code coverage reports

Generate the following outputs:

**`/app/report.json`**

```json
{
  "operations": [{"operationId": "...", "method": "...", "path": "..."}, ...],
  "operation_dependency_graph": {"<opId>": ["<depOpId>", ...], ...},
  "tool_metrics": {
    "<tool>": {
      "operations_covered": 0,
      "total_operations": 0,
      "operation_coverage_ratio": 0.0,
      "unique_faults": 0,
      "status_code_distribution": {"2xx": 0, "4xx": 0, "5xx": 0},
      "branch_coverage": 0.0,
      "line_coverage": 0.0,
      "method_coverage": 0.0
    }
  },
  "z_scores": {
    "<tool>": {
      "operation_coverage": 0.0,
      "fault_detection": 0.0,
      "branch_coverage": 0.0,
      "composite": 0.0
    }
  },
  "ranking": ["best_tool", ...],
  "badges": {"gold_api_tester": "<tool>", "bug_hunter": "<tool>"}
}
```

**`/app/odg.dot`** — Operation Dependency Graph in Graphviz DOT format.

**`/app/odg.svg`** — SVG rendering of the graph.

## Definitions

- **Operations**: every API operation in the specification (each `operationId`).
- **Operation coverage**: an operation is covered when a tool achieved a 2xx response for it.
- **Unique faults**: distinct 5xx errors per tool, deduplicated by the `message` field in the response body.
- **Code coverage**: aggregate branch, line, and method coverage ratios from JaCoCo XML.
- **ODG**: directed graph of inter-operation data-flow dependencies derived from schema analysis. Edge A→B: a property in A's success response matches a request parameter or body property of B by name and type. No self-loops. Every operation appears as a key (even with zero outgoing edges).
- **Composite scoring**: population Z-score normalization of `operations_covered`, `unique_faults`, and `branch_coverage` across tools. Composite = sum of the three Z-scores. Zero standard deviation → zero Z-scores.
- **Ranking**: descending composite.
- **Badges**: `gold_api_tester` = highest composite; `bug_hunter` = most unique faults.