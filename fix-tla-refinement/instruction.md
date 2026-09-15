`/app/TwoPhase.tla` contains a TLA+ specification of the Two-Phase Commit protocol, intended to refine the abstract Transaction Commit specification in `/app/TCommit.tla` (`TC == INSTANCE TCommit`). The TLC model checker jar is at `/app/tla2tools.jar` (invoke with `java -cp /app/tla2tools.jar tlc2.TLC`).

The specification contains multiple interacting bugs that cause safety violations. The model configuration at `/app/TwoPhase.cfg` is incomplete — it checks only `TPTypeOK` without deadlock suppression, so TLC on the current configuration will not expose the safety issues. The reference specification `/app/TCommit.tla` is correct and defines the abstract protocol semantics that `TwoPhase.tla` must implement.

**Deliverables:**

- **`/app/TwoPhase.tla`**: Fix all bugs so the specification correctly implements the Two-Phase Commit protocol as abstracted by `/app/TCommit.tla`. The corrected specification must satisfy both `TPTypeOK` and `TPConsistent` (already defined in the file). Additionally, define a new invariant operator `TPSafety` that strengthens `TPConsistent` by asserting that any committed resource manager implies both a committed transaction manager state and the presence of the commit broadcast in the message pool. This invariant must hold on the corrected specification.

- **`/app/TwoPhase.cfg`**: Complete model configuration with `CONSTANT RM = {r1, r2, r3}` (model values), `SPECIFICATION TPSpec`, invariants `TPTypeOK`, `TPConsistent`, and `TPSafety`, and `CHECK_DEADLOCK FALSE`.

- **`/app/results.json`**: JSON object with integer keys `distinct_states`, `total_states`, and `state_depth` extracted from a successful TLC run (exit code 0).