The `/app/` directory contains an RTL (Register Transfer Language) optimization framework modeled on CompCert's verified compiler. Programs are control-flow graphs stored as JSON under `/app/programs/`. The IR is defined in `/app/rtl.py`. CompCert Coq source files documenting the formal optimization semantics are in `/app/compcert_ref/`.

A multi-command analysis toolkit `rtl-toolkit` is on PATH (source at `/app/tools/rtl-toolkit`). It provides CFG inspection (`inspect`), step-by-step execution tracing (`trace`), GraphViz DOT output (`dot`), semantic validation between original and optimized programs (`validate`), structural IR diffing (`diff`), and optimization statistics (`stats`). Run `rtl-toolkit --help` and `rtl-toolkit <command> --help` to learn its interface. Use `jq` for querying the JSON IR and `dot` (GraphViz) for rendering CFG visualizations (e.g. `rtl-toolkit dot prog.json | dot -Tsvg -o cfg.svg`).

Three optimization passes in `/app/passes.py` are unimplemented stubs. Implement them:

- **`constant_propagation(func)`** — Propagate compile-time constant values through the program. Fold operations on constant operands into constant assignments. Resolve conditional branches with statically-determined conditions by replacing `Icond` with `Inop` targeting the taken successor. Must correctly handle control-flow merges where both paths assign the same constant (diamond patterns).

- **`dead_code_elimination(func)`** — Remove instructions that compute values never used by any subsequent live instruction or return. Replace dead `Iop` nodes with `Inop`. Eliminate unreachable nodes. Must handle cascading dead code where removing one instruction exposes further dead definitions.

- **`branch_tunneling(func)`** — Collapse chains of `Inop` instructions. Redirect all instruction successors to skip directly to the first non-`Inop` target in each chain. Must handle cycles.

The pipeline (`/app/pipeline.py`) composes passes in order and iterates to fixpoint. Semantic equivalence is mandatory: `interpret(original, args) == interpret(optimized, args)` for all programs and inputs. Use the toolkit to analyze programs, trace execution, compare before/after structures, and validate your implementations.