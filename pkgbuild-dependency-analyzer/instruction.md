`/app/ecosystem/` contains 10 directories, each with an Arch Linux PKGBUILD. These form an interconnected package ecosystem with split packages, virtual providers, epoch-aware versioning, and conflict declarations.

Several PKGBUILDs use advanced bash constructs that defeat regex-based parsing: one uses a computed `_prefix` variable in `pkgname` array elements and inside `package_*()` function dependencies; another uses `eval`/`declare -f` dynamic function generation — the same pattern the Flutter AUR package uses — where `package_*()` functions are synthesized at source time from template functions via string substitution on `_group` prefixes.

Create `/app/audit-pipeline.sh` that produces three artifacts:

## `/app/repo.db` — SQLite package database

Tables:
- `packages(name TEXT PRIMARY KEY, pkgbase TEXT, pkgver TEXT, pkgrel TEXT, epoch INTEGER DEFAULT 0, full_version TEXT, pkgdesc TEXT)`
- `package_arch(package_name TEXT, arch TEXT)`
- `depends(package_name TEXT, dep_name TEXT, dep_constraint TEXT, dep_type TEXT)` — dep_type is `depends`, `makedepends`, or `optdepends`; dep_name is the bare name; dep_constraint is the full original string
- `provides(package_name TEXT, provided_name TEXT, provided_version TEXT)` — NULL version when unversioned
- `conflicts(package_name TEXT, conflict_name TEXT)`

`full_version`: `epoch:pkgver-pkgrel` when epoch > 0, else `pkgver-pkgrel`. Split packages inherit pkgbase-level epoch/pkgver/pkgrel/arch/makedepends; `package_*()` functions can override pkgdesc, depends, provides, conflicts, optdepends.

## `/app/depgraph.dot` and `/app/depgraph.svg` — dependency graph

Graphviz DOT graph rendered to SVG via `dot -Tsvg`:
- One node per package, labeled with name and full_version
- Solid edges for runtime depends, dashed for makedepends (in-ecosystem only)
- Packages with unsatisfiable in-ecosystem version constraints: `shape=doubleoctagon`
- Conflict relationships: red bidirectional edges (`dir=both, color=red`)
- Split packages grouped in `subgraph cluster_<pkgbase>` blocks

## `/app/audit.json` — JSON audit report

```json
{
  "package_count": <int>,
  "pkgbase_count": <int>,
  "packages": {
    "<name>": {
      "pkgbase": "<str>", "pkgver": "<str>", "pkgrel": "<str>",
      "epoch": <int>, "full_version": "<str>", "pkgdesc": "<str>",
      "arch": ["..."], "depends": ["..."], "makedepends": ["..."],
      "provides": ["..."], "conflicts": ["..."], "optdepends": ["..."]
    }
  },
  "build_order": ["<pkgbase>", ...],
  "issues": [
    {"type": "CONFLICT", "packages": ["<p1>","<p2>"], "detail": "<str>"},
    {"type": "VERSION_MISMATCH", "package": "<pkg>", "dependency": "<dep_string>", "available_version": "<ver>"}
  ],
  "installable_groups": [["<pkg>", ...], ...]
}
```

**build_order**: topologically sorted pkgbase names — each pkgbase's in-ecosystem makedepends and runtime depends (across all its sub-packages) must appear earlier. Exclude pkgbases whose packages have unsatisfiable in-ecosystem version constraints.

**issues**: `CONFLICT` for each pair where one package names the other (or a name the other provides) in its `conflicts` array — self-conflicts produce no pair. `VERSION_MISMATCH` when an in-ecosystem dependency has a version constraint that no ecosystem package or virtual provider satisfies.

**installable_groups**: maximal co-installable package sets — no two packages in a group may conflict, and packages with unsatisfiable dependencies are excluded from all groups.