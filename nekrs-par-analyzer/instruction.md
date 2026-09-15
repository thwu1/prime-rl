Build `/app/nekrs_auditor.py` — a pre-flight auditor for nekRS spectral element CFD simulations that cross-validates a Gmsh mesh file against a nekRS `.par` configuration file.

**Invocation**: `python3 /app/nekrs_auditor.py <case_dir>`

Eight case directories exist under `/app/cases/`: `rbc_valid`, `rbc_broken`, `rans_valid`, `rans_broken`, `cht_valid`, `cht_broken`, `pipe_valid`, `pipe_broken`. Each contains a `*.par` (nekRS configuration) and a `mesh.msh` (Gmsh MSH format). The four valid cases have correct configurations. The four broken cases each contain multiple deliberate `.par` errors. The `gmsh` Python module is pre-installed. A `.par` format reference is at `/app/docs/nekrs_par_reference.md`.

The tool must output a single JSON object to stdout with three top-level keys:

**`mesh`** — statistics extracted from the mesh file:
- `num_elements`: count of 2D surface elements
- `dimension`: mesh dimension
- `bounding_box`: `[[xmin, ymin, zmin], [xmax, ymax, zmax]]`
- `min_element_size`, `max_element_size`: element areas
- `mean_quality`: element quality metric in [0, 1]
- `boundary_groups`: map of physical group name to line-element count

**`config`** — parsed and validated `.par` configuration:
- `physics_type`: one of `rbc`, `rans_ktau`, `cht`, `pipe_flow`, `channel_flow`, `generic`. Physics type detection must succeed even when validation errors are present.
- `polynomial_order`: integer
- `time_stepper`: string (e.g. `tombo2`)
- `scalars`: list of declared scalar names (lowercase)
- `material_props`: evaluated numeric values keyed by property name (`viscosity`, `rho`, `diffusionCoeff`, `transportCoeff`, `diffusionCoeffSolid`, `transportCoeffSolid` as applicable); mathematical expressions in `.par` values must be evaluated to floats
- `nondim_params`: derived non-dimensional parameters as applicable to the detected physics type — may include `Re`, `Ra`, `Pr`, `conductivity_ratio`, `flow_direction`
- `boundary_conditions`: map of field name (lowercase) to list of BC type strings (e.g. `{"velocity": ["zeroDirichlet", "zeroDirichlet"]}`)
- `errors`: list of `{"code": "<ERROR_CODE>", "message": "<description>"}` objects
- `valid`: `true` when `errors` is empty, `false` otherwise

**`diagnostics`** — cross-validated resolution metrics:
- `total_dof`: total spectral element degrees of freedom, i.e. `num_elements × (polynomial_order + 1)^dimension`
- `first_gll_spacing`: physical spacing from the element boundary to the first interior GLL collocation point, computed as the minimum element edge length multiplied by the normalized first-interior-node distance for the given polynomial order
- `estimated_y_plus`: wall-normal y+ at the first grid point for wall-bounded flows (numeric); `null` when no bulk Reynolds number applies (e.g. buoyancy-driven convection)

**Validation error codes** the tool must detect and report (conditions documented in the reference):
`MISSING_SCALAR_SECTION`, `EXPRESSION_ERROR`, `INVALID_TIMESTEPPER`, `MISSING_VARIABLE_VISCOSITY`, `NEGATIVE_PROPERTY`, `MISSING_SOLID_DIFFUSION`, `MISSING_SOLID_TRANSPORT`, `INVALID_POLYNOMIAL_ORDER`, `INVALID_FLOW_DIRECTION`, `SCALING_COEFF_OUT_OF_RANGE`

Exit 0 regardless of detected issues in the analyzed files.