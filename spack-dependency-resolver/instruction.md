Implement a dependency resolver for an HPC-style package management system.

The package repository is defined in `/app/packages.json` and contains 11 packages with version lists, variant definitions, conditional dependencies, declared conflicts, and virtual package provider relationships (three virtuals: `mpi`, `blas`, `lapack`). Data models and utilities (`Version`, `VersionRange`, spec parser, `PackageRepo`) are provided in `/app/models.py`. The `clingo` solver is installed and available via `import clingo`.

Create two files:

**`/app/encoding.lp`** — Logic program that clingo will load to perform constraint resolution.

**`/app/resolver.py`** — Python module exporting:

```python
from models import ResolvedDAG

class Resolver:
    def __init__(self, repo_path: str): ...
    def resolve(self, spec_str: str) -> ResolvedDAG: ...
```

The `resolve` method accepts a spec string of the form `name[@version_range] [+variant] [~variant] [key=value] [^dep_constraint ...]` and returns a `ResolvedDAG` (defined in `models.py`) containing `specs` (dict mapping package names to `ConcreteSpec`), `edges` (list of `(parent, child)` dependency tuples), and `build_order` (topological ordering where each package appears after all its dependencies).

Resolution semantics:
- Latest satisfying version preferred
- First-listed provider preferred for virtual packages
- Default variant values unless overridden by user or required by a dependency
- Conditional dependencies activated by variant values (`+var`/`~var`) or self-version ranges (`@lo:hi`)
- Required dependency variants enforced transitively through the DAG
- Multi-provider consistency: a concrete package providing multiple virtuals must be selected for all of them
- User `^dep` constraints override provider selection and tighten version/variant constraints
- Raise `UnsatisfiableSpecError` or `ConflictError` (from `models.py`) when constraints cannot be satisfied