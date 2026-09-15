The file `/app/config.json` defines five steady-state slab-on-grade ground heat transfer cases inspired by the BESTEST-GC methodology. Each case specifies a 2D vertical cross-section through the soil beneath a strip foundation, including geometry (slab, foundation wall, optional insulation, soil), material thermal conductivities, and boundary conditions (indoor/outdoor/deep temperatures, symmetry, adiabatic surfaces).

Your task: compute the total steady-state floor heat loss per unit length (W/m) for each case and produce the following outputs:

1. `/app/results.json` — JSON object mapping each case name to its numeric heat loss value (W/m):
   `{"base": 42.15, "high_conductivity": 55.3, ...}`

2. `/app/results.db` — SQLite database with table:
   ```sql
   CREATE TABLE results (
       case_name TEXT PRIMARY KEY,
       heat_loss_W_per_m REAL NOT NULL,
       num_nodes INTEGER NOT NULL,
       num_elements INTEGER NOT NULL
   );
   ```
   Each row stores the case name, computed heat loss (matching `results.json`), and mesh statistics (node and element counts).

3. `/app/meshes/<case_name>.msh` — A gmsh-format mesh file for each of the five cases (`base.msh`, `high_conductivity.msh`, `small_slab.msh`, `shallow_ground.msh`, `insulated.msh`).

Physical consistency requirements across cases:
- All heat losses must be strictly positive
- `high_conductivity` heat loss > `base` heat loss
- `small_slab` heat loss < `base` heat loss
- `shallow_ground` heat loss > `base` heat loss
- `insulated` heat loss < `base` heat loss, with ratio `insulated / base` < 0.85

Each heat loss value must be within 5% relative error of an independent reference solution.