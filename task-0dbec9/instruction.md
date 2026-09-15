Implement a 2D Binary Space Partitioning (BSP) tree compiler inspired by the Doom engine's rendering pipeline. The program must read map data containing 2D line segments, construct a valid BSP tree, and answer front-to-back traversal queries from arbitrary viewpoints.

## Program Interface

Create an executable at `/app/bsp_engine` that accepts two arguments:

    /app/bsp_engine <input_map.json> <output_result.json>

## Input Format

Map JSON files are at `/app/maps/map1.json` through `/app/maps/map4.json`. Each contains:

```json
{
  "segments": [
    {"id": 0, "x1": 0, "y1": 0, "x2": 1000, "y2": 0},
    ...
  ],
  "queries": [
    {"x": 500, "y": 500},
    ...
  ]
}
```

Segments are 2D line segments (walls). Queries are viewpoint positions.

## Output Format

Write results to the specified output JSON path:

```json
{
  "bsp": <BSP_TREE>,
  "stats": {
    "num_nodes": <int>,
    "num_leaves": <int>,
    "num_segs": <int>,
    "max_depth": <int>
  },
  "query_results": [
    {
      "viewpoint": {"x": <float>, "y": <float>},
      "seg_order": [
        {"id": <int>, "x1": <float>, "y1": <float>, "x2": <float>, "y2": <float>, "line_id": <int>},
        ...
      ]
    },
    ...
  ]
}
```

The BSP tree is a recursive JSON structure. Internal nodes:

```json
{
  "type": "node",
  "split": {"x1": <float>, "y1": <float>, "x2": <float>, "y2": <float>},
  "front": <BSP_TREE>,
  "back": <BSP_TREE>
}
```

Leaf nodes:

```json
{
  "type": "leaf",
  "segs": [<seg_objects>]
}
```

Each seg has: `id` (unique within tree), `x1`, `y1`, `x2`, `y2`, `line_id` (original segment ID).

## BSP Construction Requirements

- Splitting planes must be chosen from the lines defined by input segments.
- Segments that span a splitting line must be split at the intersection point into two sub-segments.
- Each leaf must contain only segments that do not cross each other.
- Every input segment must be fully covered by the sub-segments (segs) in the tree.
- The "front" side of a splitting line is defined by the positive side of the cross product: given split direction `(dx, dy) = (x2-x1, y2-y1)`, a point `(px, py)` is on the front if `dx*(py-y1) - dy*(px-x1) > 0`.

## Traversal Requirements

For each query viewpoint, traverse the BSP tree front-to-back: at each internal node, determine which side of the splitting line the viewpoint is on and visit that side first, then the other side. `seg_order` lists all segments in the tree in the order they are encountered during this traversal.

## Maps

- `map1.json`: Rectangle (4 segments, no crossings)
- `map2.json`: Perpendicular cross (2 segments, 1 crossing)
- `map3.json`: 3x3 grid (6 segments, 9 crossings)
- `map4.json`: Room with interior walls (8 segments, 4 crossings)

Write results to `/app/results/`.