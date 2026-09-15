The network operations platform at `/app/` manages production network topologies in the SQLite database `/app/netops.db`. An automated remediation pipeline stalled before completing — explore the platform's logs (`/app/logs/`), configuration (`/app/config/`), and protocol documentation (`/app/docs/`) to understand the pipeline's purpose, then manually produce all required deliverables.

The platform's pipeline is expected to produce three categories of output:

**Database results** — One row per flagged topology in the `optimization_results` table of `/app/netops.db`, containing the optimal link-swap solution as defined by the protocol documentation.

**Audit report** — A JSON report at `/app/reports/audit.json` produced by querying the completed database with `sqlite3` in JSON output mode and reshaping the result with `jq`. Must contain a top-level `"topologies"` array sorted by topology id, where each element has: `"id"`, `"name"`, `"node_count"`, `"original_diameter"`, `"optimized_diameter"`, and a `"swap"` object with keys `"remove_src"`, `"remove_dst"`, `"add_src"`, `"add_dst"`.

**Change visualization** — A Graphviz DOT file at `/app/reports/topology_changes.dot` depicting the `branch_office_alpha` topology with the removed link annotated `[style=dashed color=red]` and the added link annotated `[style=bold color=green]`. Render to `/app/reports/topology_changes.svg` using the `dot` CLI.