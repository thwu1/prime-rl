Three source files at `/app/src/` contain stub implementations that throw `Error`. Complete them so that all verification tests pass.

**Files to complete:**

- `/app/src/TransformedGeometry2d.ts` — A `Geometry2d` subclass wrapping any geometry with a 2×3 affine transformation matrix (`MatModel`). All abstract and overridden methods must produce geometrically correct world-space results under arbitrary affine transforms (non-uniform scaling, shear, rotation, translation, and their compositions). The `transform(matrix)` method returns a new `TransformedGeometry2d` with the composed transformation (this geometry's matrix applied first, then the given matrix).

- `/app/src/Group2d.ts` — A `Geometry2d` subclass that holds multiple child geometries. Must implement all abstract and overridden methods.

- `/app/src/ellipseIntersect.ts` — Implement `intersectLineSegmentEllipse(a1, a2, center, rx, ry, rotation)`. Returns all intersection points between a line segment and an ellipse (center, semi-axis lengths `rx`/`ry`, rotation in radians), or `null` if none exist.

The foundation library is provided in `/app/src/`. Study the `Geometry2d` base class, `Mat`, `Vec`, `Box`, and other modules to understand method contracts, inherited defaults, and existing patterns.

The existing codebase may contain defects that only manifest when your implementations integrate with the foundation code. You are responsible for ensuring all tests pass, which may require diagnosing and fixing issues beyond the three stub files.

**Verification:**

```
cd /app && npm install && npx tsx /tests/run_tests.ts
```

All tests must pass (exit code 0).
