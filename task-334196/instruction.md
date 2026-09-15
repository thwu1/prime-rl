The CSS cascade engine at `/app/` has diverged from its previously-correct behavior. At git tag `v1.0`, the engine produced correct computed styles for the test DOM tree. Subsequent development introduced multiple regressions across engine modules — the engine now produces incorrect output for certain CSS scenarios.

The CSS specification reference is at `/app/css_cascade_spec.md`. Property metadata (including inheritance behavior) is in `/app/properties.json`.

The engine also lacks support for the CSS `unset` keyword, which must be implemented.

**Deliverables:**

1. Restore the engine so its output matches the `v1.0` expected output exactly.

2. Implement the `unset` CSS-wide keyword per the specification.

3. Write `/app/conformance_report.json` with the following structure:
   - `issues_found`: array of objects, each with `module` (engine source filename, e.g. `cascade.py`), `description` (what was wrong and why), and `regression_commit` (the full git hash of the commit that introduced the regression)
   - `fix_groups`: array of objects, each with `modules` (array of engine filenames whose bugs interact) and `rationale` (explanation of why these bugs must be co-fixed — fixing one without the other produces no improvement or exposes a previously-masked failure)
   - `keywords_implemented`: array of CSS-wide keywords you implemented