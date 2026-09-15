# BSP Task Format Specification

## Input: `/app/map.wad`

A PWAD (Patch WAD) binary file containing four lumps of 2D map geometry data, inspired by the classic Doom WAD format.

### WAD Structure

**Header** (12 bytes):

| Offset | Size | Type      | Description                              |
|--------|------|-----------|------------------------------------------|
| 0      | 4    | char[4]   | Magic identifier: `PWAD`                 |
| 4      | 4    | int32 LE  | Number of lumps in the directory          |
| 8      | 4    | int32 LE  | Byte offset of directory from file start  |

**Directory** (located at the offset given in the header; each entry is 16 bytes):

| Offset | Size | Type      | Description                      |
|--------|------|-----------|----------------------------------|
| 0      | 4    | int32 LE  | Byte offset of lump data         |
| 4      | 4    | int32 LE  | Size of lump data in bytes       |
| 8      | 8    | char[8]   | Lump name (null-padded ASCII)    |

### Input Lumps

**VERTEXES** — Array of vertex records (8 bytes each):

| Offset | Size | Type      | Description   |
|--------|------|-----------|---------------|
| 0      | 4    | int32 LE  | x coordinate  |
| 4      | 4    | int32 LE  | y coordinate  |

Vertex index = position in array (0, 1, 2, ...).

**LINEDEFS** — Array of linedef records (16 bytes each):

| Offset | Size | Type      | Description                          |
|--------|------|-----------|--------------------------------------|
| 0      | 4    | int32 LE  | linedef_id                           |
| 4      | 4    | int32 LE  | v1 (start vertex index)              |
| 8      | 4    | int32 LE  | v2 (end vertex index)                |
| 12     | 2    | int16 LE  | front_sector                         |
| 14     | 2    | int16 LE  | back_sector (-1 = one-sided/solid)   |

**SECTORS** — Array of sector records (20 bytes each):

| Offset | Size | Type      | Description                    |
|--------|------|-----------|--------------------------------|
| 0      | 4    | int32 LE  | sector_id                      |
| 4      | 16   | char[16]  | name (null-padded ASCII)       |

**VIEWPNTS** — Array of viewpoint records (8 bytes each):

| Offset | Size | Type      | Description   |
|--------|------|-----------|---------------|
| 0      | 4    | int32 LE  | x coordinate  |
| 4      | 4    | int32 LE  | y coordinate  |

---

## Output 1: `/app/output/bsp_tree.json`

A recursive JSON object representing the BSP tree.

### Internal Node

```json
{
  "type": "node",
  "split_line": {
    "x1": <number>, "y1": <number>,
    "x2": <number>, "y2": <number>
  },
  "front": <node or leaf>,
  "back": <node or leaf>
}
```

The splitting plane is derived from `split_line`:
- Direction vector: `(dx, dy) = (x2 - x1, y2 - y1)`
- Unit normal: `(nx, ny) = (-dy / L, dx / L)` where `L = sqrt(dx^2 + dy^2)`
- Plane offset: `d = -(nx * x1 + ny * y1)`
- Plane equation: `nx * x + ny * y + d = 0`
- **Front** side: `nx * x + ny * y + d > 0`
- **Back** side: `nx * x + ny * y + d < 0`
- Points with `nx * x + ny * y + d == 0` are on the plane and treated as **front**.

### Leaf Node

```json
{
  "type": "leaf",
  "subsector_id": <non-negative integer>,
  "segs": [
    {
      "x1": <number>, "y1": <number>,
      "x2": <number>, "y2": <number>,
      "linedef_id": <integer>,
      "front_sector": <integer>,
      "back_sector": <integer>
    }
  ],
  "polygon": [[<x>, <y>], [<x>, <y>], ...]
}
```

Each seg is a (possibly split) portion of an original linedef. `linedef_id` references the original linedef's `linedef_id` from the LINEDEFS lump. Every leaf must contain at least one seg. `subsector_id` values must be unique non-negative integers across all leaves.

The `polygon` field contains the vertices of the convex region assigned to this subsector by the BSP spatial partition, listed in counter-clockwise order. Each vertex is an `[x, y]` coordinate pair. The polygon must have at least 3 vertices, be convex, and have positive area. All seg endpoints in the leaf must lie within or on the boundary of this polygon.

---

## Output 2: `/app/output/traversals.json`

```json
{
  "traversals": [
    {
      "viewpoint": {"x": <number>, "y": <number>},
      "subsector_order": [<int>, <int>, ...]
    }
  ]
}
```

One entry per viewpoint from the VIEWPNTS lump, in the same order. `subsector_order` lists all subsector IDs in front-to-back order (nearest first). Each subsector ID appears exactly once. At each internal node, visit the child on the same side as the viewpoint first (front if distance >= 0).

---

## Output 3: `/app/output/adjacency.json`

```json
{
  "adjacency": [
    {
      "subsector_a": <int>,
      "subsector_b": <int>,
      "shared_edge": [[<x1>, <y1>], [<x2>, <y2>]]
    }
  ]
}
```

Each entry represents a pair of adjacent subsectors whose convex polygons share a non-degenerate boundary edge. Constraints:

- `subsector_a < subsector_b` (canonical ordering)
- Each pair appears at most once
- `shared_edge` contains the two endpoints of the shared boundary segment
- The shared edge must have positive length and lie on both polygons' boundaries
- The adjacency graph must be connected (all subsectors reachable from any other)

---

## Output 4: `/app/output/bsp_output.wad`

A PWAD file with the same header/directory structure as the input, containing three lumps: `NODES`, `SEGS`, `SSECTORS`.

### NODES Lump

Array of BSP internal node records (24 bytes each). Nodes are stored in pre-order traversal order (root = index 0).

| Offset | Size | Type       | Description                |
|--------|------|------------|----------------------------|
| 0      | 4    | float32 LE | split line x1              |
| 4      | 4    | float32 LE | split line y1              |
| 8      | 4    | float32 LE | split line x2              |
| 12     | 4    | float32 LE | split line y2              |
| 16     | 4    | int32 LE   | front_child                |
| 20     | 4    | int32 LE   | back_child                 |

**Child encoding:**
- `child >= 0`: index into the NODES array (internal node child)
- `child < 0`: leaf subsector with `subsector_id = -(child + 1)`

Examples: child = -1 means subsector_id 0; child = -5 means subsector_id 4.

### SEGS Lump

Array of seg records (24 bytes each). Segs are grouped by subsector — all segs belonging to the same subsector are contiguous.

| Offset | Size | Type       | Description    |
|--------|------|------------|----------------|
| 0      | 4    | float32 LE | x1             |
| 4      | 4    | float32 LE | y1             |
| 8      | 4    | float32 LE | x2             |
| 12     | 4    | float32 LE | y2             |
| 16     | 4    | int32 LE   | linedef_id     |
| 20     | 4    | int32 LE   | subsector_id   |

### SSECTORS Lump

Array of subsector records (12 bytes each), ordered by `subsector_id`.

| Offset | Size | Type      | Description                            |
|--------|------|-----------|----------------------------------------|
| 0      | 4    | int32 LE  | subsector_id                           |
| 4      | 4    | int32 LE  | num_segs                               |
| 8      | 4    | int32 LE  | first_seg_index (index into SEGS lump) |

**Consistency requirements:**
- Number of NODES records = number of internal nodes in `bsp_tree.json`
- Number of SSECTORS records = number of leaves in `bsp_tree.json`
- Total SEGS count = sum of all `num_segs` in SSECTORS
- `first_seg_index + num_segs <= total SEGS count` for each SSECTOR
- Subsector IDs in SSECTORS must match those in `bsp_tree.json`
- Root node (NODES index 0) split line must match root of `bsp_tree.json`

---

## Output 5: `/app/output/bsp_tree.svg`

SVG visualization of the BSP tree structure, generated by rendering a Graphviz DOT description using the `dot` command-line tool.

Requirements:
- Internal nodes depicted as rectangles showing split line coordinates
- Leaf nodes depicted as ellipses showing subsector ID and seg count
- Edges labeled `front` and `back`
- Valid SVG viewable in a browser
