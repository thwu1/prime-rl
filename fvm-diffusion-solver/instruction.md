Implement a cell-centered finite volume method (FVM) solver for the steady-state variable-coefficient diffusion equation on a 2D unstructured triangular mesh of an annular domain with perturbed interior nodes.

## Starting state

- `/app/mesh_generator.py` generates triangular meshes at refinement levels 1-4. Interior nodes are randomly perturbed, producing non-orthogonal cells. Usage: `python3 mesh_generator.py <level> [seed]`.
- `/app/problem_spec.py` defines the PDE: `div(kappa * grad(T)) = S`, the variable diffusion coefficient `kappa(x,y)`, source term `S(x,y)`, manufactured exact solution `T_exact(x,y)`, Neumann flux function, and the analytical inner-boundary flux constant.

## Requirements

Create `/app/solver.py` callable as:
```
python3 /app/solver.py <mesh_json_file> <output_json_file>
```
It must read the mesh JSON, solve the PDE with Dirichlet conditions on the inner boundary and Neumann conditions on the outer boundary, and write a JSON output containing at minimum `cell_temperatures` (list of floats), `l2_error` (float), and `inner_boundary_flux` (float).

Then run the solver across mesh levels 1, 2, and 3 (with default seed 42) and produce `/app/results.json`:
```json
{
  "l2_errors": [e1, e2, e3],
  "mesh_sizes": [h1, h2, h3],
  "convergence_order": p,
  "inner_boundary_flux_finest": Q
}
```
where `mesh_sizes` are characteristic mesh spacings (`sqrt(total_domain_area / n_cells)`), `convergence_order` is computed from the ratio of the two finest levels, and `inner_boundary_flux_finest` is the total diffusive flux integral through the inner boundary on the level-3 mesh.

The solver must achieve second-order spatial convergence on the perturbed meshes.