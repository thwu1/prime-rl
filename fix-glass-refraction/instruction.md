`/app/rt.py` is a Whitted-style ray tracer that handles spheres and planes with Phong shading, shadows, reflection, and refraction. The scene in `/app/scene.yaml` uses cubes, cylinders, shape groups, and constructive solid geometry (CSG) operations — none of which the renderer supports.

`/app/render_scene.py` is a hardcoded diagnostic script that does not read the scene file. `/app/Makefile` defines the rendering pipeline:

- `make render` — runs the renderer; must produce `/app/output.ppm` (P3 format, 100×75, max color value 255)
- `make verify` — validates the output image using `pamfile` (checks 100 by 75 dimensions) and `ppmhist` (requires ≥ 20 distinct colors)

Extend the ray tracer and rendering pipeline so that both `make render` and `make verify` succeed. All new shape and operation types must be defined in `/app/rt.py`, following the existing `Shape` base class pattern (subclass `Shape`, implement `local_intersect(ray)` and `local_normal_at(point)`).

## Required Classes and Interfaces

**`Cube`** (subclass of `Shape`):
- `local_intersect(ray)` — axis-aligned bounding box intersection using slab method; returns list of `Intersection` objects
- `local_normal_at(point)` — returns the face normal for the dominant axis

**`Cylinder`** (subclass of `Shape`):
- `local_intersect(ray)` — infinite cylinder wall intersection (quadratic), plus cap intersections when closed
- `local_normal_at(point)` — wall normal or cap normal (y-axis direction)
- Properties: `.minimum` (default `-inf`), `.maximum` (default `+inf`) for truncation; `.closed` (default `False`) for end caps

**`Group`** (subclass of `Shape`):
- `add_child(shape)` — adds a child shape and sets `child.parent = self`
- `local_intersect(ray)` — intersects ray with all children, returns merged sorted results
- Parent-chain normal computation: `normal_at` must traverse the parent chain to correctly transform normals for nested groups (world → object and object → world coordinate conversions through each ancestor)

**`CSG`** (subclass of `Shape`):
- Constructor: `CSG(operation, left, right)` where `operation` is `"union"`, `"intersection"`, or `"difference"`
- `local_intersect(ray)` — intersects both children, then filters using `filter_intersections`
- `filter_intersections(xs)` — walks the sorted intersection list tracking inside/outside state for left and right children, keeping only intersections permitted by `intersection_allowed`

**`intersection_allowed(op, lhit, inl, inr)`** — standalone function (not a method). Takes the operation string, whether the intersection hit the left child, and whether the hit point is inside the left/right children. Returns `True`/`False` per CSG boolean rules for all 24 combinations across union/intersection/difference.

## Output Requirements

The rendered `/app/output.ppm` must be a valid P3 PPM file (100×75, max 255) containing a scene with visible color variety: distinct red-dominant pixels (the cube), blue-dominant pixels (the CSG sphere), and gray/neutral pixels (the floor plane). The Makefile `verify` target must pass.