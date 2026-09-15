A FoundationDB simulation test suite has produced trace data from three runs, four restart test specification pairs, and two reproduction scenarios. Investigate all artifacts and produce five structured JSON result files in `/app/results/`.

## Environment

- `/app/traces/` — Three run directories (`run_001/`, `run_002/`, `run_003/`), each containing XML trace logs and `metadata.json` with test path, seed, and buggify setting
- `/app/test_specs/` — Four restart test TOML spec pairs (`*_1.toml` / `*_2.toml`)
- `/app/fdb_knowledge.db` — SQLite database with tables: `binary_registry` (versions, paths, protocol version hex IDs), `protocol_compat` (compatibility matrix), `failure_signatures` (error categorization templates), `recovery_requirements` (per-role minimums)
- `/app/orchestrator_input.json` — Two reproduction scenarios with version line constraints
- `/app/output_schemas.json` — JSON schemas defining required output structure

## Deliverables

Produce five JSON files in `/app/results/` conforming to `/app/output_schemas.json`:

**`run_001_analysis.json`, `run_002_analysis.json`, `run_003_analysis.json`** — Per-run forensic analysis. For each run: determine pass/fail, identify phases (restart tests have 2, fast tests have 1), extract per-phase recovery state transitions, detect processes and their roles, collect genuine errors (Severity >= 40) while excluding injected faults, and note SaveAndKill activity. Failed runs require root cause analysis including protocol version hex identifiers looked up from `binary_registry` and compatibility status from `protocol_compat`.

**`spec_validation.json`** — Audit all four TOML spec pairs against FDB restart test conventions. Identify which pairs violate the protocol and describe the specific violations.

**`reproduction_commands.json`** — For each scenario in `orchestrator_input.json`, resolve binary paths by querying `binary_registry` for the latest patch release within each version line, then generate correct `fdbserver -r simulation` command lines with proper binary selection (old/new depends on upgrade vs. downgrade direction), seed management (phase 2 = phase 1 seed + 1), and `--restarting` flag semantics.

## Tools

`xmlstarlet`, `jq`, `sqlite3`, Python 3 standard library.