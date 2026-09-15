The directory `/app/` contains a broken billiard shot optimization project. The goal is to get the full pipeline working so that running `python3 /app/optimize.py` produces a valid `/app/result.json`.

Given a billiard table configuration (defined in `/app/problem.json`), the system must find cue ball launch velocity `(vx, vy)` that drives a target ball to a specified location, minimizing the squared distance between the target ball's final simulated position and the desired location.

The project has four components that must all function correctly:

1. **C library** (`/app/cdual/`): Arithmetic library source code is provided but the `Makefile` has issues preventing compilation into the shared library that the Python layer expects to load.

2. **Python wrapper** (`/app/dual_c.py`): A skeleton that must interface with the compiled C library to expose a usable Python class with full arithmetic operator support.

3. **Physics simulator** (`/app/physics.py`): A 2D rigid-body simulator with incomplete collision handling. Ball-ball collision response and wall/cushion reflections are unimplemented.

4. **Optimizer** (`/app/optimize.py`): A skeleton that must use the simulation pipeline to find optimal cue ball velocity and produce the output file.

Examine each file carefully to understand what is broken or missing. The problem specification in `/app/problem.json` defines the table, ball positions, target, and simulation parameters. A pure-Python reference implementation exists at `/app/dual.py` but is not used by the pipeline.

`/app/result.json` must contain: `optimal_vx` (float), `optimal_vy` (float), `final_cost` (float below `4.0`), `selected_optimizer` (`"gd"` or `"adam"`), `gd_final_cost` (float), `adam_final_cost` (float). The `selected_optimizer` must be whichever achieved the lower `final_cost`.