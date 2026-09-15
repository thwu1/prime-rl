A multi-module SoC formal verification setup in `/app/` contains:

- `design_hierarchy.json` — module tree with parent-child relationships, signal lists, and an inter-signal dependency graph
- `properties.json` — 18 formal property specifications referencing design signals
- `proof_structure.json` — 16 proof decomposition nodes using five strategy types (assume-guarantee, case-split, partition, stopat, edit-node)
- `jg_states.tcl` — design state configuration using TCL namespaces, procedures, and conditional feature flags that compute the actual valid state enumerations

Produce `/app/proof_analyzer.py` — a single entry point (`python3 /app/proof_analyzer.py`) that generates the artifacts below.

## Required Output Artifacts

### `/app/design_states_resolved.json`

The fully resolved design state enumerations. The TCL script contains feature-gated conditional logic; the output must reflect the states that result when all flags are evaluated as configured.

### `/app/analysis_report.json`

**`assume_guarantee_analysis`** — `dependency_graph`: for each AG node, the sorted list of AG nodes it depends on. `cycles`: all groups of mutually dependent AG nodes (each group a sorted list; outer list sorted by first element).

**`case_split_analysis`** (keyed by node ID) — `complete` (bool), `state_variable`, `covered_values` (sorted), `missing_values` (sorted). A case split is complete if it covers every valid value of its state variable according to the resolved design states.

**`stopat_analysis`** (keyed by node ID) — `valid` (bool), `errors`: each stopat module must exist in the design hierarchy and be a child of the node's declared scope module.

**`edit_node_analysis`** (keyed by node ID) — `valid` (bool), `errors`: a non-null `base_node` must reference an existing proof node.

**`coi`** (keyed by property ID) — sorted list of all signals in each property's cone of influence (the full set of signals the property depends on, directly and transitively through the signal dependency graph).

**`abstraction_soundness`** (keyed by stopat node ID) — whether the stopat abstraction is semantically sound with respect to its target properties. An unsound abstraction removes signals that the proof relies on. Fields: `sound` (bool: true iff all stopat modules exist AND no signal in the target properties' COI belongs to an abstracted module), `compromised_signals` (sorted list of affected COI signals), `missing_modules` (sorted list of stopat modules absent from the hierarchy).

**`proof_coverage`** — which of the 18 properties have at least one structurally valid proof path through schedulable nodes (including properties reachable through partition sub-properties). Fields: `covered` (sorted), `uncovered` (sorted), `coverage_ratio` (float, 4 decimal places).

**`execution_schedule`** — classify all 16 proof nodes into four mutually exclusive, exhaustive categories (each a sorted list): `schedulable`, `cyclic`, `invalid`, `blocked`.

### `/app/proof_dependency.dot` and `/app/proof_dependency.svg`

Graphviz DOT digraph of the proof dependency topology. Every proof node appears as a DOT node. Dependency edges between AG nodes are labeled with the relevant guarantee ID. The SVG must be rendered from the DOT file using the `dot` layout engine.