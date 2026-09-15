Implement a complete linear eigenvalue buckling analysis for 3D Euler-Bernoulli beam-column frames in `/app/fem_buckling.py`. A stub with the function signature already exists there.

The module must export:

```python
def elastic_critical_load_analysis(node_coords, elements, boundary_conditions, nodal_loads):
```

**Parameters:**

- `node_coords`: `(N, 3)` float ndarray of global `[x, y, z]` node coordinates (0-indexed rows).
- `elements`: list of dicts, each with keys `node_i`, `node_j` (int, 0-based end-node indices), `E`, `nu`, `A`, `I_y`, `I_z`, `J`, `I_rho` (float, material/section properties), and `local_z` (unit ndarray(3,) or None, reference vector for element local axis orientation).
- `boundary_conditions`: `dict[int, list[int]]` mapping node index to a 6-element binary list where 1 = fixed and 0 = free. Omitted nodes are fully free.
- `nodal_loads`: `dict[int, list[float]]` mapping node index to `[Fx, Fy, Fz, Mx, My, Mz]`. Omitted nodes have zero load.

**Returns:** `(critical_load_factor, mode_shape)` where `critical_load_factor` is the smallest positive eigenvalue λ from the generalized buckling eigenproblem on the free DOFs, and `mode_shape` is the `(6*N,)` global buckling mode vector with constrained DOFs set to zero.

**Requirements:**

- Each element has 6 DOF per node ordered `[u_x, u_y, u_z, theta_x, theta_y, theta_z]`.
- When `local_z` is `None`, default to global z `[0,0,1]` as the orientation reference unless the beam is parallel to global z, in which case use global y `[0,1,0]`.
- The analysis must correctly account for the full influence of all internal member forces on stability — not only axial compression but also bending moments and torsion. An implementation that neglects these coupling effects will produce incorrect results under combined loading.
- Results must be frame-orientation-invariant: rigidly rotating the entire structure (coordinates, loads, reference vectors) must yield identical critical load factors and correspondingly rotated mode shapes.