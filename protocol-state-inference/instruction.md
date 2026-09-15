`/app/` contains artifacts from two fuzzing campaigns (`aflnet` vs `baseline`) targeting a custom FTP-like protocol server:

- `/app/traces/training/` — 20 session recordings (JSON). Each has `session_id`, `fuzzer`, and ordered `interactions` with `request` (str), `response_code` (int), `timestamp_ms` (int).
- `/app/traces/test/` — 5 unlabeled sessions (same interaction format, no `fuzzer` field).
- `/app/config.json` — Campaign metadata.

Running `python3 /app/analyzer.py` must produce all of the following in `/app/output/`:

**`state_machine.json`** — Behavioral model of the protocol inferred from all training sessions. Each distinct `response_code` encountered defines a state; the pre-interaction state is `"INITIAL"`. States with no outgoing transitions are terminal. Format: `{"states": [...], "initial_state": "INITIAL", "transitions": [{"from": str, "request": str, "to": str}, ...], "terminal_states": [...]}`

**`minimized_machine.json`** — Minimal equivalent model: states that are behaviorally indistinguishable must be collapsed. Lexicographically smallest member represents each equivalence class. Format: `{"num_states": int, "num_transitions": int, "merge_groups": [{"representative": str, "members": [str, ...]}, ...], "transitions": [{"from": str, "request": str, "to": str}, ...]}`

**`minimized.dot`** — Valid Graphviz digraph of the minimized model, renderable via `dot -Tsvg /app/output/minimized.dot -o /app/output/minimized.svg`. The SVG must also be produced.

**`metrics.json`** — Per-session coverage against the full (non-minimized) model, with ratios to 4 decimal places. Format: `{"num_states": int, "num_transitions": int, "num_terminal_states": int, "per_session": [{"session_id": str, "fuzzer": str, "states_visited": int, "transitions_exercised": int, "state_coverage": float, "transition_coverage": float}, ...]}`

**`comparison.json`** — Statistical comparison of per-session coverage distributions between the two fuzzers. Format: `{"state_coverage": {"mann_whitney_u": float, "p_value": float, "a12_effect_size": float, "superior_fuzzer": str}, "transition_coverage": {<same fields>}}`

**`anomalies.json`** — Classify each test session as conforming or anomalous relative to the inferred model. For anomalous sessions, report the first unexplainable interaction. Format: `[{"test_id": str, "conforming": bool, "first_anomaly_index": int, "anomalous_transition": {"from": str, "request": str}}, ...]` (omit anomaly fields for conforming sessions)