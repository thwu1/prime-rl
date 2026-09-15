The `/app/` directory contains a multi-language graph analytics pipeline that
processes a dynamic graph dataset from `/data/` and writes results to `/app/output/`.
The pipeline consists of:

- A **Rust graph engine** (`/app/graph-engine/`) built with Cargo that performs
  incremental triangle counting via delta queries as the graph evolves through
  batched edge insertions and deletions
- A **Python script** (`/app/scripts/truss.py`) that computes truss decomposition
  on the final graph state
- A **Makefile** (`/app/Makefile`) that orchestrates building the Rust component
  and running all pipeline stages

The pipeline is currently broken. There are bugs in the Rust source code, a
configuration issue in the build orchestration, and the truss decomposition
component is unimplemented. Diagnose and fix all issues so that `make all`
from `/app/` produces output files in `/app/output/` satisfying the correctness
criteria defined in `/app/SPEC.md`.