A satellite CDH (command and data handling) flight software topology is specified at `/app/spec/`:

- `components.json` — component definitions with typed ports, array sizes, directions, and match specifiers
- `port_types.json` — port type registry and compatibility metadata
- `topology.json` — baseline topology (10 instances and their connections)
- `runtime.json` — rate-group CPU budgets and per-component worst-case execution times
- `fpp_rules.md` — the six FPP connection rules governing valid topologies
- `requirements.md` — mission change requirements (REQ-1 through REQ-7)

Redesign the topology to incorporate all mission changes from `requirements.md` while satisfying every FPP connection rule and every rate-group CPU budget constraint. All 10 baseline instances and their critical operational connections (command dispatch, command sequencing, rate driver wiring, and primary command dispatcher match specifier relationships) must be preserved. Three new instances must be added: `fileDownlink` (`Svc.FileDownlink`), `bufferMgr` (`Svc.BufferManager`), and `backupCmdDisp` (`Svc.CommandDispatcher`).

Every active/queued component in the final topology must have: health monitoring connections (with correctly matched ping indices per the Health component's match specifier), telemetry output wired to the telemetry channel, event/text-event logging wired to the event logger, time output wired to the time source, and command dispatch coverage from both the primary and backup dispatchers. Buffer-dependent components must be connected to their buffer manager.

## Required outputs

**`/app/redesigned_topology.json`** — Complete redesigned topology using the same JSON schema as the baseline. Must satisfy all six FPP connection rules, all rate-group budgets, and all requirements.

**`/app/topology.dot`** — Graphviz DOT graph of the topology. All instances as nodes; connections as edges colored by port-type category: command=`red`, health=`green`, telemetry=`blue`, events=`orange`, time=`purple`, scheduling=`brown`. Must be valid DOT parseable by graphviz.

**`/app/topology.svg`** — SVG rendering of the DOT file (valid SVG markup required).

**`/app/scheduling_report.json`** — Per-rate-group analysis. Each entry: `period_ms`, `budget_ms`, `members` (array of `{instance, port, wcet_ms}`), `total_wcet_ms`, `utilization_pct` (= total_wcet_ms / budget_ms * 100), `feasible` (boolean). All rate groups must be feasible.

**`/app/design_decisions.json`** — JSON array of at least 3 objects with `decision` and `rationale` keys documenting architectural trade-offs.