A binary WAD file at `/app/map.wad` encodes 2D map geometry: vertices, linedefs (wall segments with sector assignments), sectors, and viewpoints. The binary format specification is in `/app/FORMAT.md`.

Parse the WAD and construct a BSP (Binary Space Partition) tree from the line segments. Splitting lines must be collinear with an original linedef. Segments that straddle a splitting plane must be split at the intersection point. Leaf subsectors must form convex groups of segments.

For each leaf subsector, reconstruct the convex polygon boundary of the spatial region it occupies within the map's axis-aligned bounding box. These polygons form a complete spatial partition of the bounding box: their areas must sum to the bounding box area with no interior overlap, and every subsector's segments must lie within its polygon boundary.

Compute a subsector adjacency graph: two subsectors are adjacent when their convex polygons share a non-degenerate boundary edge. The adjacency graph must be connected and include the shared edge coordinates.

Compute front-to-back traversal orderings for all viewpoints encoded in the WAD.

Produce five outputs:

- `/app/output/bsp_tree.json` — BSP tree with convex polygon vertices per leaf (format in FORMAT.md)
- `/app/output/traversals.json` — viewpoint traversal orderings (format in FORMAT.md)
- `/app/output/adjacency.json` — subsector adjacency graph with shared edge data (format in FORMAT.md)
- `/app/output/bsp_output.wad` — BSP results packed into a binary PWAD (record layouts in FORMAT.md)
- `/app/output/bsp_tree.svg` — Graphviz visualization of BSP tree hierarchy, rendered from DOT via `dot`

All outputs must be mutually consistent: the binary WAD must encode the same tree structure as the JSON, traversal orderings must match independent re-traversal of the JSON tree, polygon geometry must be valid across all leaves, and adjacency edges must lie on actual polygon boundaries.