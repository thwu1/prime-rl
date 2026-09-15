The NAFEMS LE1 benchmark defines a plane-stress analysis of an elliptic membrane. The problem specification is at `/app/nafems_le1_spec.json`.

The domain is the first-quadrant portion of an annular region bounded by two concentric ellipses (inner semi-axes 2.0 m and 1.0 m; outer semi-axes 3.25 m and 2.75 m). An outward-normal pressure of 10 MPa is applied on the outer elliptical boundary. Symmetry conditions constrain the two straight edges (u_x = 0 on x = 0, u_y = 0 on y = 0). The inner elliptical boundary is traction-free.

Conduct a mesh convergence study: solve the problem at a minimum of 4 mesh refinement levels using quadratic finite elements for plane stress. For each mesh level:

- Save the generated mesh in Gmsh `.msh` format to `/app/meshes/level_<N>.msh` (e.g., `level_1.msh`, `level_2.msh`, etc.)
- Extract both σ_yy and σ_xx at evaluation point D = (2.0, 0.0) m
- Compute the maximum displacement magnitude across all nodes in the domain

Write results to `/app/results.json` in this exact format:

```json
{
  "benchmark": "NAFEMS_LE1",
  "convergence_study": [
    {"level": 1, "num_elements": <int>, "num_nodes": <int>, "sigma_yy_MPa": <float>, "sigma_xx_MPa": <float>, "max_displacement_mm": <float>},
    {"level": 2, "num_elements": <int>, "num_nodes": <int>, "sigma_yy_MPa": <float>, "sigma_xx_MPa": <float>, "max_displacement_mm": <float>},
    {"level": 3, "num_elements": <int>, "num_nodes": <int>, "sigma_yy_MPa": <float>, "sigma_xx_MPa": <float>, "max_displacement_mm": <float>},
    {"level": 4, "num_elements": <int>, "num_nodes": <int>, "sigma_yy_MPa": <float>, "sigma_xx_MPa": <float>, "max_displacement_mm": <float>}
  ]
}
```

Results must demonstrate convergence toward the known NAFEMS reference solution as the mesh is refined (decreasing error with increasing element count). Element counts must strictly increase across levels.

CalculiX (`ccx`) and Gmsh are available in the environment.