Implement a Java intraprocedural dataflow analysis engine at `/app/src/` that processes three-address code (TAC) programs, computes reaching definitions, live variables, and available expressions, and produces control-flow graph visualizations.

Examine the TAC files in `/app/tac/` and the interface in `/app/src/AnalysisEngine.java`. The TAC format includes labels, constant and copy assignments, binary operations, conditional branches, unconditional gotos, and return statements. Labels do not receive statement indices; all other lines are indexed from 0.

**Build**: `cd /app && make compile` then `make run FILE=/app/tac/straight.tac`

**Executable JAR**: Produce `/app/analyzer.jar` runnable via `java -jar /app/analyzer.jar <tac-file>` for JSON output and `java -jar /app/analyzer.jar --dot <tac-file>` for Graphviz DOT control-flow graph output.

**DOT CFG output**: A valid Graphviz `digraph` named after the method. Each statement is a node with its index as numeric id and label `"<index>: <statement_text>"`. Directed edges represent all CFG successor relationships.

**Batch script**: Create an executable `/app/analyze.sh` taking a directory path argument. It must use the JAR to analyze every `.tac` file, write per-method JSON to `/app/results/<method>.json`, generate per-method CFG SVGs at `/app/results/<method>_cfg.svg` via the `dot` command, and write a combined JSON array to stdout.

**JSON schema** (per file, to stdout):
```json
{
  "method": "<name>",
  "statements": ["<stmt0>", ...],
  "reaching_definitions": {"in": [[...], ...], "out": [[...], ...]},
  "live_variables": {"in": [[...], ...], "out": [[...], ...]},
  "available_expressions": {"in": [[...], ...], "out": [[...], ...]}
}
```

Each analysis has `in` and `out` arrays indexed by statement number:

- **reaching_definitions**: sorted lists of `["variable", defining_stmt_index]` pairs; sort by variable name first, then by index
- **live_variables**: sorted lists of variable name strings
- **available_expressions**: sorted lists of `"x OP y"` strings; only binary assignments where both operands are variables produce tracked expressions

All inner lists sorted lexicographically.

**Interface**: Implement both methods of `AnalysisEngine`. Wire into `/app/src/Main.java` to handle the `--dot` flag.

**Constraints**:
- Analyses must produce correct results for programs with branches, loops (including nested), diamond CFGs, and multiple merge points
- Verification includes hidden TAC programs not shipped in `/app/tac/`
- Use the provided `/app/Makefile` for compilation
