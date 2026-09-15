Arch Linux PKGBUILDs at `/app/pkgbuilds/` define an interconnected package ecosystem with split packages, versioned provides/conflicts, epochs, and bash variable expansions. Build a pipeline that produces three outputs when run as `bash /app/pipeline.sh`:

**`/app/output/report.json`** with keys:
- `packages`: package name -> `{base, version, depends, makedepends, provides, conflicts, pkgdesc}` for every package. Split packages inherit base version. Version format: `epoch:pkgver-pkgrel` when epoch is set, else `pkgver-pkgrel`.
- `providers`: virtual package name -> list of concrete providing packages.
- `conflict_groups`: list of `[pkg_a, pkg_b]` pairs with mutual conflict declarations.
- `circular_dependencies`: list of cycle groups (including cycles through virtual provides chains).
- `build_order`: topological ordering of all non-cyclic packages respecting dependency constraints (use alphabetical tiebreaking when multiple packages could appear next).
- `vercmp_results`: compare these pairs using pacman's vercmp semantics: `[["1:2.5.0-1","3.2.0-1"],["14.1","3.2.0"],["2:5.0.1-1","5.0"],["1.0.0","1.0"],["3:1.0.0-1","2:99.99-1"],["1.0.0alpha","1.0.0beta"],["1.0.0","1.0.0a"]]` — each result entry: `[left, right, result]` where result is -1, 0, or 1.
- `install_simulation`: resolve installing `["scheduler","webapp"]` — recursively resolve the full dependency tree, select among multiple providers by highest vercmp of provided virtual version, validate version constraints, detect conflicts. Result: `{install_order: [...], provider_selections: {virtual: chosen_concrete}, unresolved: [...]}`

**`/app/output/srcinfo/<pkgbase>.SRCINFO`** for each pkgbase, conforming to the format produced by `makepkg --printsrcinfo`: all bash variables and parameter expansions must be fully resolved to their concrete values.

**`/app/output/deps.svg`** — dependency graph: packages as nodes (labeled `name\nversion`), solid edges for dependencies, dashed red edges for conflicts, dotted blue edges for provides.

Run: `bash /app/pipeline.sh`