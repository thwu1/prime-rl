A local Arch Linux-style package repository at `/app/repo/` contains six package directories, each with a `PKGBUILD` file. The PKGBUILDs exercise a range of real-world packaging patterns: variable expansion, brace expansion in source arrays, split packages with per-sub-package function overrides, epoch-versioned dependencies, and multi-architecture support.

The repository has no `.SRCINFO` files, no dependency analysis, and no integrity validation. Your goal is to produce a complete audit of this repository as described below.

## Expected artifacts

- **`.SRCINFO` for every package** — Each package directory in `/app/repo/<dir>/` must contain a `.SRCINFO` file that faithfully represents its PKGBUILD's fully-resolved metadata, matching the format, field ordering, and section structure that `makepkg --printsrcinfo` would produce (tab-indented fields, non-indented section headers, resolved variable/brace expansions, correct per-sub-package sections for split packages).

- **`/app/results/dependency_graph.json`** — A JSON object mapping every installable package name (including sub-packages from split packages) to a sorted array of its dependencies satisfiable within this repository (where a dependency name matches a `pkgname` or `provides` entry of another in-repo package).

- **`/app/results/issues.json`** — A JSON array of objects (`package`, `type`, `description`) reporting packaging integrity problems: checksum count mismatches between source and checksum arrays (`checksum_mismatch`), circular inter-package dependencies (`circular_dependency`), and versioned dependency constraints unsatisfiable by the versions present in this repository (`version_conflict`).

- **`/app/results/install_order.json`** — A JSON array of package names in a valid dependency-respecting topological installation order. Packages involved in dependency cycles must be excluded.