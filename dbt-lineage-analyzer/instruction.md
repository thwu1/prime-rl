A data team's dbt project has failed across three consecutive nightly CI runs. The CI system executes models against a cached manifest from the last successful build — recent source changes are not reflected. Targeted re-runs of individual failed nodes have not helped. The team suspects manifest staleness and dependency drift are involved, but does not know the full picture.

Investigate the pipeline state using all available data sources and produce a forensics report.

**Available data** (read-only, `/data/`):

- `models/` — current dbt SQL model source files organized by layer
- `manifest.json` — dbt manifest from the last successful CI build
- `pipeline_runs.db` — SQLite database recording per-node execution outcomes across three runs
- `selectors.yml` — CI selector definitions
- `dbt_project.yml` — project metadata

**Output**: Write `/app/forensics.json` — a JSON object with these keys:

- `drift` — object containing:
  - `added`: sorted list of model short names present as source SQL files under `models/` but absent from the manifest as model nodes
  - `removed`: sorted list of model short names present as model nodes in the manifest but with no corresponding source SQL file
  - `dependency_changes`: dict mapping each model whose upstream `ref()` dependencies in source SQL differ from the manifest's `depends_on` to a sorted list of dependency short names present in source but absent from the manifest

- `root_causes_by_run` — per `run_id`, sorted list of `unique_id`s for failure-originating nodes: those that failed or were skipped but whose failures did not result from upstream dependency failures in that same run

- `persistent_root_cause` — sorted `unique_id`s that are root causes in at least one run and have a non-passing status in every run in the database

- `transient_root_causes` — sorted `unique_id`s that are root causes in at least one run and pass in at least one run

- `masked_in_runs` — for each persistent root cause, sorted list of `run_id`s where it had a non-passing status but was not identified as a root cause (its independent failure was masked by concurrent upstream failures)

- `stale_selectors` — sorted selector names from `selectors.yml` whose `fqn`-method value (after stripping dbt graph operators) references a model not present in the source tree

- `blocking_dependency` — the short name of the model referenced via `ref()` in the persistent root cause's source SQL but absent from that node's `depends_on` in the manifest

- `cascade_impact` — for each root cause `unique_id` appearing in any run: the count of distinct model nodes (not tests, not seeds) transitively downstream of it in the manifest dependency graph

- `fix_priority` — all root cause `unique_id`s sorted by `(number of runs where the node appears as a root cause) * cascade_impact` descending, with alphabetical tiebreaking on `unique_id`