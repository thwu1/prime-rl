The TypeScript project at `/app/` is a boolean polygon clipping library. Given two polygon geometries and an operation, it should compute the geometric boolean result (intersection, union, difference, or XOR) and return it as a MultiPolygon.

The implementation is incomplete and produces no correct results. Fix it so that all four operations work correctly.

**Setup and execution:**

```
cd /app && npm install
npx tsx /app/run_op.ts <op_code> '<subject_json>' '<clipping_json>'
```

Operation codes: 0=intersection, 1=union, 2=difference, 3=xor. Inputs are Polygon (`[[[x,y],...]]`) or MultiPolygon (`[[[[x,y],...],...],...]`) coordinate arrays. Output is MultiPolygon JSON to stdout, or the string `null` for empty results.

The public API in `/app/src/entry.ts` exports `intersection`, `union`, `diff`, and `xor` — each accepts two `Geometry` arguments and returns `MultiPolygon | null`.

**Success criteria:**

- Overlapping convex polygons: all four operations produce correct areas
- Non-overlapping polygons: intersection returns null; union preserves both shapes as separate polygons
- Overlapping triangles: correct fractional intersection area
- Full containment (small polygon inside large): difference produces one polygon with exterior ring and hole ring (exactly 2 rings)
- Adjacent polygons sharing a collinear edge: union merges into single polygon; intersection is null or zero-area
- Concave polygons (e.g., L-shaped): all operations produce correct areas
- MultiPolygon inputs: operations handle multi-polygon subjects and produce correct combined results
- Area identity holds for every polygon pair: area(A) + area(B) = area(intersection) + area(union)
- All output rings are closed (first vertex equals last vertex, minimum 4 points per ring)
- GeoJSON fixtures in `/app/fixtures/` produce consistent results across all operations with valid area relationships
