The file `/app/problem_spec.py` defines a variable-coefficient anisotropic Helmholtz equation with a manufactured exact solution on the unit square [0,1]²:

```
-div(K(x,y) grad u) + c(x,y) u = f(x,y)    in [0,1]^2
u = 0                                         on boundary
```

where K is a 2×2 spatially-varying symmetric positive definite diffusion tensor, c is a reaction coefficient, u is the manufactured exact solution, and f is the corresponding forcing function. A triangular mesh generator is provided in `/app/mesh.py`.

Implement a finite element solver that uses the functions from `/app/problem_spec.py` and supports both P1 (linear) and P2 (quadratic) Lagrange elements on triangular meshes. The solver must correctly handle the tensor-valued anisotropic diffusion coefficient through appropriate Jacobian transformations from reference to physical space. For P2 elements, construct edge midpoint DOFs with consistent local-to-global numbering matching your reference element node ordering.

Run a convergence study on meshes with n = 4, 8, 16, 32 subdivisions per side for both P1 and P2 elements. Compute the L2 error against the manufactured exact solution at each refinement level. Write results to `/app/results.json`:

```json
{
  "p1": {"mesh_sizes": [4, 8, 16, 32], "errors": [e1, e2, e3, e4], "convergence_rate": <float>},
  "p2": {"mesh_sizes": [4, 8, 16, 32], "errors": [e1, e2, e3, e4], "convergence_rate": <float>}
}
```

Compute `convergence_rate` as the mean of log2(e_i / e_{i+1}) over the last two consecutive refinement steps (8→16 and 16→32).

The results must demonstrate theoretically expected convergence behavior. The P1 convergence rate must lie in [1.7, 2.5] (consistent with O(h²) in the L2 norm) and the P2 rate in [2.5, 3.8] (consistent with O(h³)). All errors must be positive and monotonically decreasing under refinement. On the finest mesh (n=32), the P1 error must be below 0.01 and the P2 error below 0.001. The P2 error on the finest mesh must be strictly smaller than the P1 error, with a P1/P2 error ratio exceeding 5.