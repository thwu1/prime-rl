Cursorless is a structural code editor that uses tree-sitter AST queries to identify code scopes (functions, classes, statements, etc.). Its test infrastructure uses a custom `.scope` fixture format — a visual annotation scheme where source code is followed by `---` and then annotated scope blocks showing ranges via `>---<` markers, line-numbered source excerpts, facet labels (`[Content]`, `[Removal]`, `[Domain]`, `[Interior]`, `[Leading]`, `[Trailing]`), and insertion delimiters.

Example `.scope` fixtures demonstrating the format are in `/app/fixtures/`. Tree-sitter query files (`.scm`) for Python scope detection are in `/app/queries/`. The `tree-sitter` and `tree-sitter-python` packages are pre-installed.

Implement `/app/scope_engine.py` — a Python module providing the following API:

- `parse_fixture(text) -> List[Scope]` — Parse `.scope` fixture text into structured `Scope` objects, each containing a `ranges` dict mapping facet names to `Range(start_line, start_col, end_line, end_col)` objects, plus an `insertion_delimiter` string.
- `render_fixture(source, scopes) -> str` — Render source code and scopes back into `.scope` fixture text with byte-for-byte round-trip fidelity.
- `map_captures_to_scopes(captures, insertion_delimiter) -> List[Scope]` — Convert tree-sitter query captures (following Cursorless naming conventions like `@name`, `@name.domain`, `@name.interior`, `@name.leading`, `@name.trailing`) into `Scope` objects with correctly derived `Removal` and `Domain` facets.
- `annotate_source(source, language, query_text) -> str` — End-to-end pipeline: parse source with tree-sitter, run a query, map captures to scopes, and render the complete `.scope` fixture output.

The module must also export `Range` and `Scope` data classes.

All tests in `/tests/test_state.py` must pass.