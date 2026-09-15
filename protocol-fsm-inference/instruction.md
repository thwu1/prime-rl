A stateful protocol fuzzing campaign has produced binary interaction traces, instrumented coverage data, and a reference protocol model for a custom file transfer protocol. Build a complete analysis pipeline that infers a behavioral model from the traces, reduces it by merging equivalent states, identifies coverage gaps against the reference, and visualizes the results.

## Data

- `/app/protocol_spec.json` — Protocol format specification (binary trace encoding, command/response code semantics, state model).
- `/app/traces/*.bin` — Binary-encoded interaction traces from the fuzzing campaign.
- `/app/coverage.db` — SQLite database with per-trace basic block coverage from the instrumented server binary.
- `/app/reference.dot` — Reference protocol state machine in Graphviz DOT format.

## Deliverables

Implement `/app/analyzer.py` that writes all results to `/app/output/`:

- **`fsm.json`** — Inferred state machine from observed trace behavior. Fields: `states` (sorted integer list), `transitions` (list of `{"from": int, "command": int, "to": int}` — unique observed triples), `num_states` (int), `num_transitions` (int).

- **`minimized_fsm.json`** — Reduced state machine with behaviorally indistinguishable states merged. Fields: `equivalence_classes` (list of sorted integer lists — the state partition), `num_states_before` (int), `num_states_after` (int), `merged_states` (equivalence classes with more than one state).

- **`coverage_analysis.json`** — Coverage gap analysis. Fields: `total_unique_blocks` (int — distinct block IDs from the coverage database), `transition_coverage` (float — fraction of reference model transitions observed in traces), `uncovered_transitions` (sorted list of `{"from": int, "command": int, "to": int}`), `per_state_trace_count` (dict: state string to count of traces visiting that state).

- **`fsm.dot`** and **`fsm.svg`** — Graphviz DOT source and rendered SVG of the inferred state machine.

- **`minimized_fsm.dot`** and **`minimized_fsm.svg`** — DOT source and rendered SVG of the minimized state machine.