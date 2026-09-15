A Python project at `/app/codebase/` uses relative imports, `__init__.py` re-exports, and cross-package dependencies. Build a Makefile-orchestrated multi-stage analysis pipeline at `/app/Makefile` that produces artifacts in `/app/output/`.

Source modules are `.py` files excluding `__init__.py`, `conftest.py`, and test files (`test_*.py`/`*_test.py`). All output paths are relative to codebase root, forward slashes, sorted alphabetically.

## Makefile Targets

**`extract`** → `/app/output/raw_imports.json`
Parse source modules via Python AST. Per source file, emit a list of import records each with: `module` (dotted name as written, with leading dots for relative imports), `names` (list of imported names), `line` (line number), `type` (`"absolute"` / `"relative"` / `"conditional"` for imports inside try/except).

**`resolve`** → `/app/output/resolved_deps.json`
Resolve raw imports to source file paths within the project. Relative imports (`from .x import y`) resolve against the importing module's package directory. Only internal project source files count. Map each source file to its sorted direct dependency list.

**`graph`** → `/app/output/deps.dot` + `/app/output/deps.svg`
Graphviz DOT representation with `subgraph cluster_<package>` groupings for each top-level package. Render SVG via `dot -Tsvg`.

**`store`** → `/app/output/analysis.db`
SQLite database with this exact normalized schema:
```sql
modules(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, package TEXT NOT NULL)
dependencies(source_id INTEGER REFERENCES modules(id), target_id INTEGER REFERENCES modules(id), import_type TEXT NOT NULL, PRIMARY KEY(source_id, target_id))
test_cones(test_path TEXT NOT NULL, module_id INTEGER REFERENCES modules(id), PRIMARY KEY(test_path, module_id))
features(feature_id INTEGER NOT NULL, module_id INTEGER REFERENCES modules(id), PRIMARY KEY(feature_id, module_id))
feature_tests(feature_id INTEGER NOT NULL, test_path TEXT NOT NULL, PRIMARY KEY(feature_id, test_path))
```

The `import_type` column in `dependencies` must reflect whether each dependency was established via an `"absolute"`, `"relative"`, or `"conditional"` import.

**`analyze`** → `/app/output/analysis.json` containing:
- `dependency_graph` — source module → sorted list of direct dependency file paths
- `test_dependency_cones` — test file → sorted list of all transitive source dependencies
- `features` — feature clusters ordered by lexicographically smallest test file in each cluster. Each feature: `id` (0-indexed), sorted `tests`, sorted `source_files`. Two tests share a feature if they share any transitive source dependency, directly or transitively through other tests sharing dependencies.
- `isolation_matrix` — N×N Jaccard similarity matrix indexed by feature id
- `minimal_disruption_sets` — feature id (string key) → smallest sorted set of source files that intersects every test cone within the feature while intersecting no test cone from any other feature. Lexicographically smallest among tied minimum-size solutions.

**`clean`** — Remove `/app/output/` contents.
**`all`** — Full pipeline with proper Make dependency ordering.