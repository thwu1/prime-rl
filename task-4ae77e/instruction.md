The file `/app/problem.yaml` defines a reliability-based design optimization (RBDO) problem for a cantilever beam under uncertain loads and material properties. It specifies beam geometry, design variable bounds, random variable distributions, probabilistic constraint formulations, and all required deliverables with their file paths and output schemas.

Read `/app/problem.yaml` and produce every deliverable it specifies:

- The simulation driver at the path given under `deliverables.simulation_driver`
- The Dakota input file at the path given under `deliverables.dakota_input_file`
- All result files listed under `deliverables.results`, written to `/app/results/`

The optimal design must minimize beam cross-sectional area while satisfying all reliability constraints at the target levels defined in the problem specification. All result files must be internally consistent with each other and with the reported optimal design.