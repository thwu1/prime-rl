Five async-finish parallel programs are provided as JSON in `/app/programs/`. The computation model — including phaser-based point-to-point synchronization with split-phase signal/wait semantics and multi-phase advancement — is specified in `/app/spec.md`. A code stub is at `/app/analyzer_stub.py`. A Makefile with errors is at `/app/Makefile`.

Implement `/app/analyzer.py` accepting program JSON paths as arguments. For each program, produce:
- `/app/results/<name>.json` — work, span, ideal parallelism, data races (format described in spec)
- `/app/graphs/<name>.dot` — computation DAG in Graphviz DOT format with edge types visually distinguished

Fix `/app/Makefile` so that `make -C /app all` runs the analyzer on every program, renders all DOT files to SVG with `dot`, and validates every result JSON with `jq`.

Three programs use only async-finish constructs; two use phaser synchronization with per-task phase counters and mode-dependent participation. Correctly modeling phaser-induced happens-before edges across phases is essential for accurate race detection.