A PyO3 Rust extension module at `/app/` implements a graph database (`graphdb`) exposing `Node`, `Edge`, and `Graph` types to Python. The module currently fails to compile and contains additional runtime defects. The Rust toolchain is pre-installed. Build with:

```
cd /app && python3 -m venv .venv && . .venv/bin/activate && pip install maturin==1.7.8 && maturin develop
```

Fix all defects in `/app/src/lib.rs` and implement the missing methods described below so the module compiles, installs, and satisfies all behavioral requirements.

**Node**
- Constructor: `Node(id: str)`. Methods: `set_property(key, value)`, `get_property(key) -> str` (raises `KeyError` if absent). Read-only `id` property, `property_count` getter.
- Equality by `id`. Must be **hashable** — usable in `set()` and as `dict` keys. Equal nodes must produce equal hashes.

**Edge**: Read-only `source`, `target`, `weight`, `label` properties.

**Graph** — fix existing methods:
- `add_node(id)`, `add_node_with_props(id, props: dict[str,str])`, `add_edge(source, target, config)` where `config` is a **plain Python dict** `{"weight": float, "directed": bool, "label": str|None}`
- `node_count()`, `edge_count()`, `has_node(id)`, `get_node(id) -> Node`, `get_neighbors(id) -> list[(str, float)]`, `node_ids() -> list[str]`, `get_edges() -> list[Edge]`
- `to_dict() -> dict` with keys `"nodes"` (list of ids) and `"edges"` (list of `(source, target, weight)` tuples)
- `shortest_path(source, target) -> (path, cost) | None` — weighted shortest path; must release the GIL during computation
- `pagerank(damping, iterations) -> dict[str, float]` — ranks must sum to `1.0` (±0.01); dangling nodes (no outgoing edges) must redistribute their rank equally across all nodes
- `len(g)` returns node count; `id in g` checks membership

**Graph** — implement new methods:
- `to_adjacency_matrix() -> (list[str], list[list[float]])` — Returns `(sorted_node_ids, matrix)` where `matrix[i][j]` is the total edge weight from node `i` to node `j` (`0.0` if absent). Multiple edges between the same pair sum their weights. Must release the GIL during computation.
- `connected_components() -> list[list[str]]` — Connected components treating all edges as undirected. Each component is a sorted list of node IDs. Outer list sorted by first element of each component. Must release the GIL during computation.

**Concurrency contract**: `Graph` uses `Mutex<GraphInner>` for interior mutability. All public methods must be callable from concurrent Python threads without `RuntimeError: Already borrowed` panics. Methods performing significant computation must release the Python GIL.
