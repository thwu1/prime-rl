Implement a marching tetrahedra isosurface extraction pipeline at `/app/mesh_pipeline.py` that extracts triangle meshes from signed distance fields and produces `/app/result.json` containing topological and geometric analysis.

The pipeline must generate a tetrahedral grid by subdividing a regular voxel grid over [-1, 1]^3 at resolution 40 into tetrahedra, evaluate SDFs at grid vertices, and extract zero-level isosurfaces via the marching tetrahedra algorithm. The subdivision scheme must produce conforming tetrahedra across cube boundaries so that the output meshes are watertight and manifold. Coincident vertices along shared tet edges must be merged, and degenerate (zero-area) triangles removed. SDF values at grid vertices that evaluate to exactly or very near zero must be perturbed to a small positive epsilon before extraction, to prevent degenerate isosurface triangles that break manifoldness.

Process three SDF scenes:

- **sphere**: `|p| - 0.6`
- **torus**: `sqrt((sqrt(x^2 + y^2) - 0.5)^2 + z^2) - 0.2`
- **csg**: `max(|p| - 0.7, 0.3 - sqrt(x^2 + y^2))` (sphere with Z-axis cylindrical hole)

For each scene, compute and write to `/app/result.json`:
```json
{
  "<scene>": {
    "num_vertices": int,
    "num_faces": int,
    "euler_characteristic": int,
    "is_manifold": bool,
    "genus": int,
    "surface_area": float,
    "centroid": [float, float, float],
    "mean_edge_length": float,
    "edge_length_std": float,
    "smoothed_edge_length_std": float
  }
}
```

`smoothed_edge_length_std` is the edge length standard deviation after 10 iterations of uniform Laplacian smoothing (umbrella operator) with step weight 0.5. `genus` is derived from Euler characteristic for closed orientable manifolds: `g = (2 - chi) / 2`. `is_manifold` requires every edge to be shared by exactly 2 faces. Only count vertices referenced by at least one face when computing Euler characteristic.

No GPU or external mesh processing libraries are available. Use only NumPy.

Run: `python3 /app/mesh_pipeline.py`