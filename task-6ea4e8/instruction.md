A Three-Address Code (TAC) interpreter is at `/app/tac_interpreter.py`, with a language spec at `/app/spec.md` and four programs in `/app/programs/`.

The programs contain unnecessary computations, unused results, predictable control flow, and other structural redundancies. Build a complete optimization pipeline that produces semantically equivalent programs with reduced instruction counts.

## Deliverables

**`/app/optimizer.py`** — reads a TAC file path as its sole argument, writes optimized TAC to stdout. Optimized output must produce identical interpreter output to the original.

**`/app/Makefile`** — orchestrates the pipeline with targets: `optimize` (writes optimized programs to `/app/optimized/<name>.tac`), `cfg` (generates Graphviz DOT control flow graphs with basic-block nodes and renders them to SVG for each program before and after optimization in `/app/cfg/` — files named `<stem>_before.dot`, `<stem>_before.svg`, `<stem>_after.dot`, `<stem>_after.svg`), `verify` (confirms semantic equivalence via interpreter output comparison), `report` (produces `/app/report.json`), and `all`.

**`/app/report.json`** — a `jq`-processable JSON array. Each element: `{"program": "<name>.tac", "original_instructions": N, "optimized_instructions": N, "reduction_pct": F, "semantic_match": true}`.

Run `make all` to produce all outputs.

## Performance Targets

- `propagation.tac` and `diamond_flow.tac` are fully reducible — collapse each to at most 5 non-PRINT/non-LABEL instructions.
- Overall instruction-count reduction across all four programs ≥ 40%.
- 60-second per-program timeout.