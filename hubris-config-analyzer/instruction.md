A Hubris RTOS application configuration for a Gimlet server board is at `/app/hubris_app.toml`. Reference documentation on Hubris IPC semantics and the required output contract is at `/app/docs/hubris_reference.md`.

Build a tool that analyzes this RTOS configuration for scheduling safety hazards and produces:

1. `/app/ipc_graph.dot` — Graphviz DOT directed graph of all IPC dependencies, with priority-inversion edges visually distinguished.
2. `/app/ipc_graph.svg` — SVG rendering produced by running `dot` on the DOT file.
3. `/app/analysis.json` — Comprehensive scheduling safety report conforming to the schema specified in the reference documentation.

The tool must correctly handle the full Hubris task-slot configuration syntax, including aliased references (inline table format).