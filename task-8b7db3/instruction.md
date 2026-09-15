A formal verification proof decomposition engine at `/app/proof_engine/` is non-functional. The engine manages hierarchical proof structures for hardware property verification, supporting five decomposition strategies (Assume-Guarantee, Case Split, Partitioning, Stopat, Helper Invariant).

The data models, strategy-specific parameter formats, and full API contract are documented in `/app/proof_engine/models.py`. The stub implementation at `/app/proof_engine/engine.py` has seven exported functions that raise `NotImplementedError`:

- `build_proof_tree`, `validate_decomposition`, `compute_schedule`, `get_proof_report`: Core proof tree construction, strategy-specific validation (cycle detection for AG/helper, Boolean satisfiability checking for case split exhaustiveness/exclusivity, transitive fanin cone computation for partition disjointness, temporal depth rewriting for stopat), global dependency scheduling, and proof reporting.
- `generate_obligations`: Produces formal proof obligations for each decomposition strategy. Each obligation is a sub-goal whose conjunction implies the original property. AG obligations carry the expressions of assumed sub-properties; case split obligations guard the property expression with the case predicate; stopat obligations rewrite bounded temporal operators (`G[0:N]`/`F[0:N]`) to use the depth limit; partition obligations restrict the signal environment to the fanin cone; helper obligations identify assumption dependencies between helper and target.
- `compute_cone_of_influence`: Computes the minimal signal environment for a property via BFS through the signal dependency graph, reporting structural cone membership, sequential depth (BFS distance from declared signals), and boundary signals (primary inputs).
- `check_compositional_soundness`: Analyzes multi-strategy compositions for soundness issues: cross-strategy circular dependency detection (error), stopat depth exceeding cone sequential depth (warning), and case split predicates using non-primary signals (warning).

The CLI tool at `/app/validate_proof.py` must process JSON proof structure files in `/app/proofs/` and produce output in `--format json`, `--format dot`, and `--format obligations` modes. The expected output schemas are documented in the CLI file's own docstring. Exit code must be 0 on successful processing, even if the proof structure is invalid.

The project is orchestrated via `/app/Makefile` with targets `test`, `validate`, `report`, `graph`, `obligations`, and `all`.

**Success criteria**: `make all` executed from `/app/` must complete without errors.

Do not modify `models.py`, `test_integration.py`, the `Makefile`, or files under `proofs/`.