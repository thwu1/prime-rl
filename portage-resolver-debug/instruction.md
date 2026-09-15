A Portage-style dependency resolver and world upgrade planner at `/app/` reads package metadata from a SQLite3 database (`/app/packages.db`, tables: `repo_packages` and `installed_packages`) and Portage configuration from `/app/portage/`. The resolver modules live under `/app/resolver/`.

The system has multiple interacting bugs across the resolver stack and missing implementations. The database layer loads dependency strings from SQLite3 and normalizes them — ensure normalization preserves all PMS-significant syntax including `:=` slot-operator specifications. The resolver uses backtracking when dependency resolution fails for newer candidates; correct cleanup of solver state during backtracking is essential for fallback to work.

Run `python3 /app/resolve.py --plan` to execute the full pipeline. It must produce three output files:

## `/app/upgrade_plan.json`

JSON with keys:

- `upgrades`: list of `{"cp", "old_version", "new_version"}` for packages with newer versions available in the same slot (choosing newest). Version comparison follows PMS: numeric components as integers, absent letter before any letter (`1.3 < 1.3a < 1.3b`), suffixes `_alpha < _beta < _pre < _rc < (none) < _p`, `-r0 == absent`.

- `newuse_rebuilds`: list of `cp` for packages (not in upgrades) where current effective USE flags differ from installed USE and the difference changes the evaluated dependency set. `make.conf` must handle `-flag` as exclusion. USE-conditional evaluation (`flag?`, `!flag?`) must process sibling conditionals independently — negation state must not leak across siblings. `|| ( dep1 dep2 )` picks the first option.

- `slot_rebuilds`: list of `cp` for packages (not in upgrades/newuse) needing rebuild because a dependency's subslot changed and they depend on it via `:=`. Propagation must be transitive through `:=` chains.

- `merge_order`: all affected `cp` in dependency-first topological order.

## `/app/strategy_comparison.json`

JSON comparing two strategies:

- `strategies.prefer_newest`: `{upgrades: [{cp, old_version, new_version}], total_upgrades: int, slot_rebuilds: int, newuse_rebuilds: int, total_merges: int}` — always choose highest version.

- `strategies.minimize_rebuilds`: same schema — prefer versions keeping current subslot when a same-subslot newer version exists, else fall back to newest. Reduces `:=` cascades.

- `recommended`: strategy name with lower `total_merges`.
- `rationale`: one-sentence explanation.

## `/app/dependency_graph.dot`

Graphviz DOT digraph with one node per package in `merge_order` (labeled with cp and version transition or change type), directed edges for dependencies between packages in the merge set, `:=` labels on slot-operator edges. Must be valid DOT parseable by `dot -Tsvg`.