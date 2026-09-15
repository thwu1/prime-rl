A formal verification proof management pipeline at `/app/` processes JasperGold-style proof decompositions for hardware verification signoff of an arbiter subsystem. The pipeline reads a proof structure definition (`/app/proof_structure.json`) and engine verification results (`/app/engine_results.csv`), then generates a signoff report at `/app/signoff_report.json` via `python3 /app/proof_mgr.py`.

The pipeline executes without errors but produces incorrect property statuses in the signoff report. Multiple interacting bugs exist across the pipeline's CSV result loading, assumption cycle analysis, strategy status propagation, and result override handling. A structural validation script at `/app/validate_proof.sh` exists but its diagnostic output checks structural patterns, not semantic correctness, and may flag valid constructs as suspicious while missing the real issues.

Debug the pipeline, fix all bugs in `/app/proof_mgr.py`, and ensure the generated signoff report is semantically correct. The correct formal verification proof decomposition semantics are:

- **Assume-Guarantee**: Sound compositional reasoning requires acyclic assumption dependencies, including transitive chains (A assumes B, B assumes C, C assumes A is circular). Circular dependencies render the decomposition unsound (`error`). When sound, the propagated status is the weakest across all children.
- **Case Split**: If any case is falsified, the property is falsified. If all cases are proven and the split is exhaustive, the property is proven. Non-exhaustive splits yield `inconclusive`.
- **Partition (Blackboxing)**: Over-approximation that preserves both full proofs and bounded proofs. A falsified child under blackboxing may be a spurious counterexample (`inconclusive`).
- **Stopat (Bounded Proof)**: A proven child within the bound yields `bounded_proven` (not a full unbounded proof). A falsified child is a real counterexample.
- **Leaf**: Base proof status sourced from the engine results CSV. When a `status_override` field is present on the leaf node in the proof structure definition, it takes precedence over the engine result.

Status strength ordering: `proven` > `bounded_proven` > `inconclusive` > `falsified` > `error`.