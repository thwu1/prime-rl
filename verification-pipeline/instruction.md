`/app/` contains infrastructure extracted from the seL4 microkernel's formal verification pipeline — a multi-architecture system that orchestrates Isabelle/HOL proof sessions via regression test specifications.

The data comprises two independent representations of the same pipeline:

- `/app/specs/*.xml` — Regression test specifications defining tests, their CPU timeouts, and dependency structure using nested XML grouping elements
- `/app/roots/*.ROOT` — Isabelle proof session definitions with parent-child relationships and inter-session dependencies
- `/app/config/exclusions.json` — Tests excluded per architecture (ARM, ARM_HYP, X64, RISCV64, AARCH64)
- `/app/parser_notes.py` — Incomplete parser fragment with partial hints about XML format semantics

No formal documentation for either file format is provided. Study the data files and parser fragment to reverse-engineer the parsing rules.

Build `/app/pipeline.py` — a CLI that analyzes this infrastructure. All subcommands emit JSON to stdout.

**`parse-sessions`** — Parse all `*.ROOT` files in `/app/roots/`. Output `{"sessions": [{name, parent, deps, theories}...], "total"}`. Sessions sorted by name; `deps` (union of parent and `sessions` block entries) and `theories` each sorted.

**`parse-tests`** — Parse all `*.xml` files in `/app/specs/`. Output `{"tests": [{name, cpu_timeout, direct_deps}...], "total"}`. Tests sorted by name; `direct_deps` sorted. `cpu_timeout` is an integer (seconds).

**`reconcile`** — Identify which names exist in both ROOT sessions and XML tests, which are ROOT-only, and which are test-only. Output `{"matched": [...], "root_only": [...], "test_only": [...], "matched_count", "root_only_count", "test_only_count"}`. Sorted lists.

**`cascade-exclude <arch>`** — Which tests cannot run for the given architecture. A test is cascade-excluded if any of its transitive dependencies in the XML test DAG are directly excluded. Output `{"directly_excluded": [...], "cascade_excluded": [...], "total_excluded_count"}`. Sorted lists.

**`critical-path <arch>`** — The critical path through the non-excluded test DAG, weighted by `cpu_timeout`. Output `{"path": [...], "total_seconds"}`.

**`cross-validate`** — For each name that appears in both ROOT sessions and XML tests, check whether the session's ROOT dependencies (filtered to only those that are themselves matched names) are covered by the XML test's transitive dependency closure. A dep is "covered" if it appears anywhere in the transitive dependencies of the corresponding XML test. Output `{"results": [{name, status, checked_deps, uncovered_deps}...], "ok_count", "mismatch_count"}`. Status is `"ok"` if uncovered_deps is empty, `"mismatch"` otherwise. Results sorted by name; dep lists sorted.

**`change-impact <arch> <change_file>`** — Read a JSON change descriptor from `<change_file>` with format `{"add_exclusions": [...], "remove_exclusions": [...]}`. Compute the cascade effect of modifying the given architecture's exclusion list. Output `{"old_runnable_count", "new_runnable_count", "delta", "newly_excluded": [...], "newly_included": [...], "old_critical_path_seconds", "new_critical_path_seconds", "critical_path_delta"}`. Sorted lists.

**`schedule <arch> <cpus>`** — Compute a list-scheduling makespan for the non-excluded DAG on `<cpus>` homogeneous processors. Output `{"makespan"}`.