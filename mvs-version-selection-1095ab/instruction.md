A Go CLI tool at `/app/mvs` performs version selection on module dependency graphs. The scaffolding (`main.go`) and a working `BuildList` function (`mvs.go`) are provided. Four stub functions in `mvs.go` must be completed: `UpgradeAll`, `Upgrade`, `Downgrade`, and `Req`.

**Graph format**: Each non-empty, non-comment (`#`) line is `<ModVer>: [<Dep1> <Dep2> ...]`. Path is the first character, version is the remainder (e.g., `B1` = path `B`, version `1`). Version `none` means absent. Versions ending in `.hidden` participate in dependency resolution but are invisible to upgrade and previous-version enumeration.

**Commands** (`./mvs <graph-file> <cmd> [args]`):

- `build <target>` — Already implemented. Selects the maximum version of every reachable module.

- `upgrade-all <target>` — Produce a build list where every reachable module (except the target) is raised to its highest available non-hidden version.

- `upgrade <target> <mod1> [mod2...]` — Produce a build list where each listed module is required at (at least) the given version. Modules not already required by the target are added.

- `downgrade <target> <mod1> [mod2...]` — Produce a build list where each listed module is constrained to at most the given version. The first argument serves as both the target and a downgrade constraint. Modules whose transitive requirements violate the constraints must be replaced with an earlier compatible version, or removed entirely if none exists. The result must be a consistent build list with no constraint violations and all transitive dependencies fully resolved.

- `req <target> [base_path1 ...]` — Compute the minimal set of direct requirements that, if used as the target's requirements, reproduce the exact same full build list. If base paths are listed, those module paths must appear in the result. Duplicate base paths are ignored.

**Output**: Space-separated module version strings. For `build`/`upgrade-all`/`upgrade`/`downgrade`: target first, then remaining modules sorted by path. For `req`: all entries sorted by path. Exclude modules with version `none`.

**Version comparison**: Lexicographic on version strings. `Max(v, "none") = v` for all v. For the target path, its version always compares as maximum.

Build with `go build -o mvs .` from `/app/`. The binary must handle cycles in the requirement graph and all edge cases exercised by the test suite.
