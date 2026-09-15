An Arch Linux system snapshot at `/app/archroot/` is in a broken state following partial upgrades (`pacman -Sy` + selective `-Sdd`), forced dependency-skipping removals (`-Rdd`), I/O corruption, and `--overwrite` installs. The transaction log is at `/app/archroot/var/log/pacman.log`.

Database locations:
- **Local package database**: `/app/archroot/var/lib/pacman/local/` (standard directory-per-package format with `desc` and `files` entries)
- **Sync repository database**: `/app/archroot/var/lib/pacman/sync/core.db` (zstd-compressed tar archive — pacman's native sync DB format; must be decompressed and extracted to access individual package `desc` entries)
- **Package metadata cache**: `/app/archroot/var/lib/pacman/package_metadata.db` (SQLite database with `package_sizes` and `repo_state` tables for download cost analysis)

Some packages use epoch-based versioning (e.g., `1:74.2-1`). Version comparison must implement pacman-compatible `vercmp` semantics: epoch takes absolute precedence over version and release segments. A package with epoch `1:4.19.0-1` is **newer** than `4.20.0-1` (epoch 1 > implicit epoch 0) despite the lower version number.

Produce the following three files:

**`/app/report.json`** — Identifies every database consistency issue:
```json
{"issues": [{"type": "<TYPE>", "package": "<name>", "details": {...}}]}
```
Types: `MISSING_DESC` (details: `{}`), `CORRUPTED_DESC` (details: `{}`), `PARTIAL_UPGRADE` (details: `{"local_version": "...", "sync_version": "...", "affected_dependents": [...]}`), `MISSING_DEPENDENCY` (details: `{"missing_dependency": "..."}`) , `FILE_CONFLICT` (details: `{"file": "...", "packages": [...]}`), `ORPHANED_PACKAGE` (details: `{}`).

**`/app/strategy.json`** — Evaluates repair feasibility and partitions work into independent groups:
```json
{
  "recommended_strategy": "targeted",
  "minimum_repair_set": ["pkg1", "pkg2"],
  "independent_repair_groups": [["pkg_a", "pkg_b"], ["pkg_c"]],
  "has_circular_dependencies": false,
  "total_repair_operations": 10,
  "recommendation_rationale": "..."
}
```
The `minimum_repair_set` is every package requiring action (upgrades, reinstalls, installs, removals, and their affected dependents). `independent_repair_groups` partitions those packages into sets whose repairs share no cross-group dependency constraints. `has_circular_dependencies` indicates whether any dependency cycle among broken packages prevents incremental repair. The recommendation should compare targeted repair count against a full `pacman -Syu` scope.

**`/app/repair.sh`** — Executable pacman commands in valid dependency order: fix base dependencies before packages depending on them.