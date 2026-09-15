A TLA+ specification modeling a distributed atomic commit protocol is at `/app/commit_protocol.tla` with its TLC model-checking configuration at `/app/commit_protocol.cfg`. The TLA+ toolchain (`tla2tools.jar`) is at `/app/tools/tla2tools.jar`.

The specification uses PlusCal (embedded in TLA+) and contains bugs that cause safety invariant violations during model checking. The invariants `Consistency` (no participant commits while another aborts) and `CommitValidity` (commit requires unanimous yes votes) are defined in the specification.

## Deliverables

**1. Diagnose and repair the specification.** Run the model checker, analyze the counterexample traces, and fix every safety violation. Save the corrected specification as `/app/commit_protocol_fixed.tla` with configuration `/app/commit_protocol_fixed.cfg`. The model checker must report zero errors on the corrected specification with both safety invariants enabled.

**2. Extend for coordinator fault tolerance.** The corrected protocol permanently blocks participants if the coordinator process fails after the voting phase. Extend the corrected specification so that all participants reach a consistent terminal state (`"committed"` or `"aborted"`) even when the coordinator crashes post-decision. Save this as `/app/commit_protocol_recovery.tla` with `/app/commit_protocol_recovery.cfg`. The extended specification must pass all safety invariants and a liveness temporal property guaranteeing that every participant eventually terminates.

**3. Write an analysis report** to `/app/analysis.json`:
```json
{
  "bugs": [
    {"id": 1, "description": "...", "fix": "...", "invariant_violated": "..."}
  ],
  "recovery_mechanism": "...",
  "liveness_property": "..."
}
```