# Scene Specification

## Scene Format

The scene is a JSON file with a single `root` node defining a hierarchical composition of shapes. Each node is either a **primitive** (leaf) or an **operation** (internal node).

## Primitives

All primitives are centered at the origin in their local coordinate frame. Each primitive defines a scalar field that returns negative values inside the shape, positive values outside, and zero on the surface boundary. Exact distance functions are required for all primitives except where noted.

### sphere
`{"primitive": "sphere", "radius": R}`
A sphere of radius R centered at origin.

### box
`{"primitive": "box", "half_extents": [bx, by, bz]}`
An axis-aligned box centered at origin extending ±bx, ±by, ±bz along each axis.

### torus
`{"primitive": "torus", "major_radius": R, "minor_radius": r}`
A torus in the xz-plane centered at origin. The tube center traces a circle of radius R in the xz-plane; the tube cross-section has radius r.

### capsule
`{"primitive": "capsule", "a": [ax,ay,az], "b": [bx,by,bz], "radius": r}`
A capsule (line segment with hemispherical caps) between points a and b with radius r.

### capped_cylinder
`{"primitive": "capped_cylinder", "radius": r, "height": h}`
A vertical capped cylinder centered at origin with radius r, extending from y = −h to y = +h.

### octahedron
`{"primitive": "octahedron", "size": s}`
A regular octahedron centered at origin with vertices at (±s, 0, 0), (0, ±s, 0), (0, 0, ±s). Each face satisfies |x| + |y| + |z| = s. The **exact** distance is required, not the simple bound (|x|+|y|+|z|−s)/√3.

### ellipsoid (bound approximation)
`{"primitive": "ellipsoid", "radii": [rx, ry, rz]}`
An ellipsoid centered at origin with semi-axes rx, ry, rz. The exact distance cannot be expressed in closed form. Use this bound:

    k0 = length(p / r)
    k1 = length(p / (r·r))
    distance ≈ k0·(k0 − 1) / k1

where `r = (rx, ry, rz)` and all operations are element-wise.

### capped_cone
`{"primitive": "capped_cone", "height": h, "r1": r1, "r2": r2}`
A capped cone (frustum) centered at origin. Bottom cap at y = −h with radius r1, top cap at y = +h with radius r2.

### pyramid
`{"primitive": "pyramid", "height": h}`
A square-base pyramid with base corners at (±0.5, 0, ±0.5) and apex at (0, h, 0). The base is a unit square in the xz-plane at y = 0.

## Operations

### translate
`{"op": "translate", "offset": [ox, oy, oz], "child": node}`
Translates the child shape by the given offset.

### rotate
`{"op": "rotate", "axis": [ax, ay, az], "angle_deg": θ, "child": node}`
Rotates the child shape by θ degrees around the given axis (right-hand rule).

### symmetry
`{"op": "symmetry", "axes": ["x", "z"], "child": node}`
Reflects the query point across the specified axes (takes the absolute value of the corresponding coordinates) before evaluating the child.

### elongate
`{"op": "elongate", "h": [hx, hy, hz], "child": node}`
Elongates the child shape along each axis. For each axis i, the child is evaluated at q_i = p_i − clamp(p_i, −h_i, h_i).

### onion
`{"op": "onion", "thickness": t, "child": node}`
Hollows the child shape into a shell: result = |f_child| − t.

### round
`{"op": "round", "radius": r, "child": node}`
Rounds edges and corners: result = f_child − r.

### smooth_union
`{"op": "smooth_union", "k": k, "children": [node1, node2, ...]}`
Polynomial smooth minimum. For two field values d1, d2:

    k' = 4k
    h  = max(k' − |d1 − d2|, 0)
    result = min(d1, d2) − h² / (4k')

For N > 2 children, fold left-to-right: smooth_union(smooth_union(d1, d2), d3), etc.

### smooth_subtraction
`{"op": "smooth_subtraction", "k": k, "children": [carved, body]}`
Smooth carving: removes `children[0]` from `children[1]`.

    smooth_subtraction(d1, d2, k) = −smooth_union(d1, −d2, k)

### smooth_intersection
`{"op": "smooth_intersection", "k": k, "children": [node1, node2]}`

    smooth_intersection(d1, d2, k) = −smooth_union(−d1, −d2, k)

### union / subtraction / intersection
Hard boolean operations: min(d1,d2), max(−d1,d2), max(d1,d2) respectively.

## Query Types

### distance
`{"id": N, "type": "distance", "point": [x, y, z]}`
Evaluate the scene's scalar field at the given point.
Output: `{"id": N, "type": "distance", "value": float}`

### normal
`{"id": N, "type": "normal", "point": [x, y, z], "epsilon": eps}`
Compute the normalized gradient of the field at the given point via symmetric central differences with step size epsilon.
Output: `{"id": N, "type": "normal", "value": [nx, ny, nz]}`

### ray_cast
`{"id": N, "type": "ray_cast", "origin": [ox,oy,oz], "direction": [dx,dy,dz], "max_t": T, "epsilon": eps}`
Cast a ray from origin along direction (which must be normalized first). Advance along the ray; at each step move by max(field_value, eps·0.5). A hit occurs when |field_value| < epsilon. Stop if t > max_t.
Output on hit: `{"id": N, "type": "ray_cast", "value": {"hit": true, "t": float, "point": [x,y,z], "normal": [nx,ny,nz]}}`
Output on miss: `{"id": N, "type": "ray_cast", "value": {"hit": false}}`
Hit normals use the same epsilon as the hit threshold.

### classify
`{"id": N, "type": "classify", "point": [x, y, z]}`
Classify as "inside" (field < −1e-6), "outside" (field > 1e-6), or "surface".
Output: `{"id": N, "type": "classify", "value": "inside"|"outside"|"surface"}`

## Required Outputs

### Query Results
Write `/app/results.json` as a JSON array of result objects, one per query, in the same order as the input queries.

### Depth-Map Render
Render `/app/render.pgm` as a depth map of the scene from the camera viewpoint defined in `/app/camera.json`.

The camera uses a standard perspective look-at model. Parameters:
- `eye`: camera position
- `target`: look-at point
- `up`: world up hint
- `fov_deg`: vertical field of view in degrees
- `width`, `height`: image dimensions in pixels
- `max_t`: maximum ray distance
- `epsilon`: surface detection threshold
- `background_value`: pixel value for rays that miss all geometry

Pixel centers are at (col + 0.5, row + 0.5). Row 0 is at the top of the image. For each pixel, construct a ray from the camera through the image plane and find the first surface intersection using the same approach as ray_cast queries.

Map hit distance to grayscale: `pixel = round(min(t / max_t, 1.0) × 255)`. Missed rays use `background_value`.

Output in ASCII PGM format:

    P2
    <width> <height>
    255
    <pixel values, row by row, top to bottom>

### PNG Render
Also produce `/app/render.png` as a PNG conversion of the depth map.

### Cross-Section Data
Evaluate the scene's field at 500 evenly-spaced points along the x-axis (y=0, z=0) from x=−3 to x=3.

Write `/app/cross_section.dat` as tab-separated values with two columns (x, field_value) and a `#`-prefixed header line.

### Cross-Section Plot
Generate `/app/cross_section.png` as a PNG line plot of the cross-section data, with x on the horizontal axis and field value on the vertical axis.
