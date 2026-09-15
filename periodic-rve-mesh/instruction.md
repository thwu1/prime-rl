A mesh generator at `/app/mesher.py` attempts to create a triply-periodic representative volume element (RVE) mesh per the specification in `/app/rve_config.json`. The script executes but the resulting mesh has multiple interacting defects.

Diagnose the defects and produce a corrected generator at `/app/mesh_rve.py` that outputs a valid mesh at `/app/rve.msh`. Running `python3 /app/mesh_rve.py` must complete non-interactively.

The specification in `/app/rve_config.json` defines the domain geometry, spherical inclusions, material labels, and mesh constraints.

**Verification criteria:**

- **Physical groups**: 3D physical groups named `Matrix`, `CenterInclusion`, and `CornerInclusion`. `CenterInclusion` has exactly 1 volume entity. `CornerInclusion` has exactly 8 volume entities (one per domain vertex, each trimmed to the domain interior). `Matrix` contains all remaining volumes.

- **Conformal interfaces**: Inclusion and matrix volumes share mesh nodes on their common boundaries.

- **Triple periodicity**: For each axis, every node on one domain face has a corresponding node on the opposite face at the unit-translated position. Node counts on paired faces must match.

- **Size grading**: Elements near inclusion-matrix interfaces are measurably smaller than elements in the bulk interior.

- **Element quality**: Minimum SICN across all elements exceeds 0.05.

- **Element type**: Only linear tetrahedra.

- **Element count**: Between 2,000 and 2,000,000.
