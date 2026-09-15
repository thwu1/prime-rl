A multi-stage pipeline at `/app/` validates Joos 1W type hierarchy declarations against 14 rules derived from the Java Language Specification (JLS Chapters 8 and 9). It uses three stages orchestrated by `/app/Makefile`:

- `/app/views.sql`: SQL views detecting structural violations (rules 1-5) and providing hierarchy edge data for the Python checker. Applied to the SQLite database at `/app/hierarchy.db`.
- `/app/checker.py`: Python checker for semantic violations (rules 6-14). Rules 6-8 are implemented but may contain bugs. The `compute_effective_methods` function and `check_override_rules` (rules 9-14) are unimplemented stubs that return empty results.
- `/app/postprocess.sh`: Merges SQL and Python violations using `jq`, producing `/app/violations.json`.

The database contains 41 type definitions spanning valid types and types violating every rule — including inheritance cycles, diamond inheritance through interfaces, transitive final method overrides, abstract method obligations across multiple inheritance levels, and types with multiple simultaneous violations.

Design and implement the missing components, and evaluate the existing code for correctness against the specification. The `compute_effective_methods` algorithm must transitively collect methods from all supertypes (following both `extends` and `implements` relationships), handle inheritance cycles safely, deduplicate methods reachable through diamond inheritance by tracking originating declarations, and let declared methods replace inherited ones with the same signature. Rules 9-14 must check declared methods against the full transitive set of inherited methods, not just direct parent declarations.

The specification is in `/data/jls_hierarchy.md` and `/app/rules.md`. Joos 1W restrictions are in `/data/joos_deviations.md`. Explore the database schema with `sqlite3 /app/hierarchy.db ".schema"`.

Run `make clean && make check` in `/app/` to execute the pipeline. The completed pipeline must produce `/app/violations.json` as a JSON array of `{"type": "<canonical_name>", "rule": <integer>}` objects covering all actual violations with no false positives.