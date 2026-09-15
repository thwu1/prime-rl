`/app/repo/` contains AUR-style PKGBUILD definitions for an interconnected package ecosystem. External distribution packages are cataloged in `/app/registry.db` (SQLite table `packages`: columns `name`, `version`, `provides`). Utility programs in `/app/tools/` include `pkgsource` (bash-based PKGBUILD parser) and `vercmp` (pacman-compatible version comparator).

A previous automated audit produced `/app/baseline_report.json`. This baseline is deficient — package metadata is misparsed in several ways and multiple classes of packaging defects go undetected.

Write `/app/audit.py` that performs a correct, comprehensive audit and outputs `/app/report.json` — a JSON object with exactly three top-level keys:

**`packages`** — object mapping each individual package name to:
```
{
  "pkgbase": "<pkgbase this package belongs to>",
  "version": "<epoch:pkgver-pkgrel; omit epoch: when epoch is 0 or absent>",
  "depends": [...], "makedepends": [...], "provides": [...], "conflicts": [...]
}
```
All split packages must appear as separate entries. Bash variable references in arrays must be expanded. Split-package `depends`/`provides`/`conflicts` must reflect per-package `package_<name>()` overrides, not global scope. `makedepends` is always global. Version constraints in dependency strings must be preserved verbatim.

**`issues`** — array of issue objects, each with a `type` field:

- `missing_dependency` — a dependency unresolvable against both the repo and `/app/registry.db`:
  `{"type": "missing_dependency", "package": "<pkg>", "missing": "<dep>"}`

- `conflicting_provides` — two or more packages from different pkgbases declare the same provides name:
  `{"type": "conflicting_provides", "packages": ["<p1>", ...], "provides": "<name>"}`

- `version_constraint_violation` — a versioned dependency (e.g. `>=3.0.0`) unsatisfied by the provider's actual version (internal or external):
  `{"type": "version_constraint_violation", "package": "<pkg>", "dependency": "<full dep string>", "actual_version": "<ver>"}`

- `circular_dependency` — a cycle in the pkgbase-level dependency graph:
  `{"type": "circular_dependency", "cycle": ["<base1>", "<base2>", ...]}`

**`build_order`** — array of pkgbase names in valid topological order, excluding pkgbases involved in circular dependencies. Dependencies must appear before dependents.