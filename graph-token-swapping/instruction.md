The `/app/` directory contains an incomplete quantum circuit routing framework. Quantum hardware constrains which qubits can interact directly — only physically adjacent qubits (connected by an edge in the device's connectivity graph) may be swapped. When a quantum program requires a specific qubit arrangement, the compiler must produce a sequence of SWAP operations along device edges to route qubits into position.

## Environment

Benchmark metadata is stored in an SQLite database at `/app/devices.db` with normalized tables for devices, benchmarks, permutations, and topology properties. Device connectivity topologies are defined as Graphviz DOT files under `/app/devices/`. The CLI tool `/app/qroute.py` integrates both data sources for benchmark listing, topology analysis, Graphviz export, JSON export, and solver validation.

Use `sqlite3` to explore the database schema and query benchmark parameters directly. Render device topologies by piping DOT output through `dot` (Graphviz) — `python3 /app/qroute.py dot <name>` outputs the DOT source. Process JSON exports with `jq` — `python3 /app/qroute.py export <name>` outputs benchmark specifications as JSON.

## Task

Implement the `solve` function in `/app/solver.py` so that the routing framework can compile qubit permutations into valid, efficient SWAP schedules across a variety of device topologies.

```python
def solve(n: int, edges: list[list[int]], perm: list[int]) -> list[list[int]]:
```

- `n` — number of qubits (labeled 0 to n−1)
- `edges` — device connectivity as a list of `[u, v]` pairs
- `perm` — target mapping: `perm[i]` is the qubit that must end at position `i`
- Returns a list of `[u, v]` swaps to execute in order

Initially qubit `i` resides at position `i`. Each swap `[u, v]` exchanges the qubits at positions `u` and `v`. Every swap must operate on an edge present in the device graph. Applying all swaps in sequence to the identity arrangement must produce the target permutation exactly.

## Benchmarks and Quality Bounds

The benchmark database specifies device topologies, target permutation mappings, and maximum allowed swap counts. Investigate the database schema, topology DOT files, and topology properties to understand each device's structural characteristics. Your solver will face linear chains (paths), fully-connected fabrics, trees of various shapes (binary, star, caterpillar), ring topologies, 2D grid layouts, and arbitrary connected graphs. The swap count for each benchmark must not exceed its configured bound — some bounds are tight (requiring the minimum possible swaps), while others permit bounded suboptimality. Devices range up to 200 qubits.

```
```