A Rust project at `/app/` implements an incremental relational query engine (semi-naive evaluation with leapfrog triejoin) and four graph analysis programs built on it.

The project compiles and all binaries run, but three programs produce incorrect numerical results due to bugs in the engine library and/or application code. A fourth program (`scc`) is an unimplemented stub that outputs placeholder zeros.

Fix all defects and complete the `scc` implementation so that every program produces correct results.

## Project Layout

- `/app/src/lib.rs` — engine library: `Relation`, `Variable`, `join_into`, `leapjoin_into`, leaper traits (`ExtendWith`, `ExtendAnti`, `FilterAnti`)
- `/app/src/bin/transitive_closure.rs` — computes reachable-pair count → `/app/output/tc_count.txt`
- `/app/src/bin/triangles.rs` — computes directed-triangle count → `/app/output/tri_count.txt`
- `/app/src/bin/reaching_defs.rs` — computes reaching-definitions pair count → `/app/output/rd_count.txt`
- `/app/src/bin/scc.rs` — stub; should compute strongly connected components, writing total SCC count to `/app/output/scc_count.txt` and largest SCC size (node count) to `/app/output/largest_scc.txt`
- `/app/data/` — input datasets (do not modify)
- `/app/Cargo.toml` — project manifest

## Constraints

- The `scc` binary must use the `datafrog_engine` library for its transitive reachability computation.
- All nodes appearing in the edge dataset must be accounted for, including singleton SCCs.