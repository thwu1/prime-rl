Parametric surface definitions are provided as JSON files in `/app/surfaces/`. Each file specifies a B-spline or NURBS surface by its degree in each parameter direction, knot vectors, a grid of 3D control points, and optional rational weights (non-null weights indicate a NURBS surface). Each file also lists evaluation parameters and query points.

Build a pipeline at `/app/pipeline.py` that reads all surface JSON files from `/app/surfaces/` and produces three categories of output:

## Geometric Analysis — `/app/output/results.json`

A JSON object keyed by surface `id`. For each surface, compute:

- **points**: The 3D surface coordinates at each `(u, v)` pair listed in `eval_params`
- **normals**: The unit surface normal vector at each evaluation parameter
- **gaussian_curvature**: The Gaussian curvature at each evaluation parameter
- **mean_curvature**: The mean curvature at each evaluation parameter
- **area**: The total surface area over the parameter domain `[0,1]^2`, with relative error below 0.5%
- **projections**: For each 3D point in `query_points`, find the closest point on the surface and report the parameter values `(u, v)`, the projected 3D point, and the Euclidean distance

## CAD Export — `/app/output/step/{surface_id}.step`

Export each surface as a valid ISO 10303-21 STEP file. The file must faithfully represent the geometry described by the surface definition.

## Finite Element Mesh — `/app/output/mesh/{surface_id}.msh`

Generate a triangulated surface mesh for each surface in Gmsh MSH format. Requirements:
- At least 200 triangular elements per surface
- Maximum element aspect ratio (longest edge / shortest edge) below 10.0

## Schema for `results.json`

```json
{
  "surface_id": {
    "points": [[x, y, z], ...],
    "normals": [[nx, ny, nz], ...],
    "gaussian_curvature": [K1, K2, ...],
    "mean_curvature": [H1, H2, ...],
    "area": float,
    "projections": [
      {"u": float, "v": float, "point": [x, y, z], "distance": float}
    ]
  }
}
```

Arrays are ordered corresponding to `eval_params` and `query_points` respectively. Normal vectors must have unit length.