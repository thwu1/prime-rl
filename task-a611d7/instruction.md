A multi-tool dependency health auditor at `/app/depcheck.py` analyzes the Python monorepo at `/app/monorepo/`. It chains `buildozer` for extracting dependency declarations from Starlark BUILD files, Python for import parsing and graph-theoretic analysis, and `graphviz` for visualization. It should reconcile declared vs. actual dependencies and produce structural insights about the dependency graph.

The monorepo contains packages with BUILD files in multiple rule formats and `module.py` source files with various import patterns. A custom macro is defined in `tools/defs.bzl`. The auditor pipeline produces incorrect or incomplete results at multiple stages.

Debug and fix `/app/depcheck.py` to produce:
- `/app/audit_report.json` — complete report conforming to `REPORT_SCHEMA` defined in the script
- `/app/dep_graph.svg` — graphviz rendering of the declared dependency graph