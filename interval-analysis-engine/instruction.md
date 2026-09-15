Programs in a custom IR language are at `/app/programs/`. A parser is at `/app/ir_parser.py` — read its source to understand the AST schema and IR syntax. The tools `dot` (graphviz), `sqlite3`, and `jq` are available.

Create `/app/analyzer.py`. When run via `python3 /app/analyzer.py`, it must:

- Analyze each `.ir` file in `/app/programs/` and for every non-internal variable (not prefixed with `__`) in `main`, determine a value range `[lo, hi]` at function exit. Ranges must safely contain every integer value the variable could hold at runtime.
- Write results to `/app/results.json`:
  ```json
  {"filename.ir": {"var_name": [lo, hi]}, ...}
  ```
  Use `"inf"` for +infinity and `"-inf"` for -infinity.
- Write results to `/app/analysis.db` — a SQLite database with table:
  ```sql
  CREATE TABLE results (
      program TEXT NOT NULL,
      variable TEXT NOT NULL,
      lo TEXT NOT NULL,
      hi TEXT NOT NULL,
      PRIMARY KEY (program, variable)
  );
  ```
- Generate a DOT-format call graph for each program at `/app/graphs/<stem>.dot` (e.g., `/app/graphs/basic.dot`), containing an edge for every static function call. Render each to SVG via `dot -Tsvg`.