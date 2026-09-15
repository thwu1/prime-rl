Implement `/app/buffer_planner.py` — a buffer memory planner that reads a computation graph JSON and produces a memory pool layout that assigns each buffer a byte offset within a per-memory-space pool, minimizing total pool size.

Invocation: `python3 /app/buffer_planner.py <graph.json> <solution.json>`

The complete I/O specification and correctness requirements are at `/app/spec.md`.

The planner must produce truly optimal (minimum possible) pool sizes for each memory space — solutions that are merely close to optimal will fail validation. Examine the tools available in the environment.