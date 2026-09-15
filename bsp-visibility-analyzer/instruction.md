A 2D indoor environment is stored in a custom binary format at `/app/map.bin`. The format specification is at `/app/format_spec.txt`. The environment consists of 17 wall segments defining three interconnected rooms (a large room with an internal pillar, a narrow corridor, and a room with a diagonal partition) and 5 viewpoint queries.

Produce the following outputs:

**`/app/results.json`** — A JSON object with these keys:

- `bsp_tree`: A BSP tree that recursively partitions the 2D space. Each split uses a line coincident with one of the input wall segments. Internal nodes: `{"type": "node", "plane_a": <float>, "plane_b": <float>, "plane_c": <float>, "front": {...}, "back": {...}}` where `(plane_a, plane_b, plane_c)` defines the line `a*x + b*y + c = 0` with `(a,b)` as unit normal. Points where `a*x + b*y + c > 0` are on the "front" side. Leaf nodes: `{"type": "leaf", "leaf_id": <int>, "segs": [{"start": [x,y], "end": [x,y], "source_wall": <id>}, ...]}`.

- `stats`: `{"num_nodes": <int>, "num_leaves": <int>, "max_depth": <int>, "total_segs": <int>, "total_splits": <int>}` where `total_splits` counts original walls that were subdivided by splitting planes.

- `traversals`: For each viewpoint, the front-to-back ordering of all leaf IDs — at each internal node the side containing the viewpoint is visited first. Format: `[{"viewpoint_id": <int>, "leaf_order": [<leaf_id>, ...]}, ...]`.

- `visibility`: For each viewpoint, the set of original wall IDs visible within the specified field of view, accounting for occlusion by nearer walls. All walls are opaque and double-sided. A wall is visible if any part of it falls within the FOV and is not fully hidden behind nearer walls. Format: `[{"viewpoint_id": <int>, "visible_walls": [<wall_id>, ...]}, ...]`.

**`/app/bsp_tree.dot`** — A Graphviz DOT file representing the BSP tree structure. Internal nodes must display their split plane equation; leaf nodes must display their leaf ID and segment count.

**`/app/bsp_tree.png`** — The DOT file rendered to PNG via the `dot` command (Graphviz is installed at `/usr/bin/dot`).

Viewpoint `angle_deg` is the look direction (0 = +X, 90 = +Y, counterclockwise). `fov_deg` is the total symmetric field of view.