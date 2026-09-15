A parallel molecular dynamics simulation at `/app/` is failing to scale efficiently across multiple processor counts. The simulation operates on a non-uniform particle distribution using spatial domain decomposition with periodic boundaries for short-range interactions.

Available resources:
- `/app/sim/` — simulation framework source code
- `/app/data/particles.h5` — particle dataset (HDF5)
- `/app/config.yaml` — simulation and platform configuration
- `/app/profiles/benchmarks.db` — performance data from prior decomposition runs (SQLite)

Previous decomposition attempts (recorded in the profile database) used suboptimal processor grid configurations. Analyze the simulation framework, particle data, and platform configuration to determine the performance-optimal 3D processor grid `(Px, Py, Pz)` for every target processor count specified in the configuration.

Write `/app/results.json` containing the optimal decomposition and all valid candidates for each processor count, with complete performance metrics:

```json
{
  "decompositions": {
    "<P>": {
      "optimal": [Px, Py, Pz],
      "T_total": "<float>",
      "T_comp": "<float>",
      "T_comm": "<float>",
      "load_imbalance": "<float>",
      "max_particles_per_rank": "<int>",
      "comm_volume": "<int>",
      "all_candidates": [
        {"grid": [Px, Py, Pz], "T_total": "<float>", "T_comp": "<float>", "T_comm": "<float>", "load_imbalance": "<float>", "max_particles_per_rank": "<int>", "comm_volume": "<int>"}
      ]
    }
  }
}
```

`all_candidates` must list every valid decomposition, sorted by ascending `T_total`. The optimal decomposition is the one with minimum `T_total`.