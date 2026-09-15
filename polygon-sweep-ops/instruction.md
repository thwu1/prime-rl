The TypeScript project at `/app/` implements boolean polygon operations (intersection, union, difference, XOR) on 2D polygons via a sweep-line algorithm. The source files under `/app/src/` contain multiple defects — incomplete stub implementations and at least one algorithmic logic error in a nominally-complete module — that prevent the pipeline from producing correct results. Identify and fix all issues across the codebase.

**CLI:**
```
cd /app && echo '{"subject":...,"clipping":...,"operation":"intersection"}' | npx tsx run_ops.ts
```

- `subject`, `clipping`: polygon coordinate arrays — array of rings, each ring an array of `[x, y]` pairs. First ring is exterior, subsequent rings are holes. MultiPolygon format (array of polygons) is also accepted.
- `operation`: `"intersection"`, `"union"`, `"difference"`, or `"xor"`.
- Output: JSON MultiPolygon coordinate array, or `null` for empty results.

**Success criteria — all four operations must produce geometrically correct output:**

- Non-overlapping polygons: intersection yields `null`.
- Correct polygon and ring counts (e.g., difference where clipping is fully contained in subject produces one polygon with exterior ring plus hole ring).
- Computed areas within 0.01 of expected values across all test polygon pairs, including axis-aligned rectangles, arbitrary triangles, and non-axis-aligned convex polygons (diamonds).
- Subject polygons carrying interior holes must be handled correctly through all four operations, preserving hole geometry in the result.
- Correct point-in-polygon membership for result geometry (points inside result regions test positive; points inside holes or outside test negative).
- All output rings properly closed (first vertex equals last vertex), minimum 4 vertices per ring.
- GeoJSON fixture files in `/app/fixtures/` processed correctly.

Run `npm install --ignore-scripts` in `/app/` before first use.
