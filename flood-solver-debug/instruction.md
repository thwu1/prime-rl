A 2D shallow water flood inundation solver at `/app/` implements the local inertial approximation for computing overland flow on a regular grid. The solver reads terrain from an ESRI ASCII DEM, computes inter-cell fluxes using q-centered momentum discretization with Manning friction, enforces boundary conditions, applies CFL-adaptive timestepping, and writes simulation results.

The project is in a non-functional state. All input data under `data/` are correct and must not be modified.

**Build and run:**
```
cd /app && cmake -B build && cmake --build build && ./build/flood_solver
```

**Required outputs** (written to `/app/`):
- `results_final.asc` — ESRI ASCII water depth map (21x15 grid)
- `results_gauges.csv` — depth time series at three gauge points (columns: time, upstream, middle, downstream)
- `results_mass.txt` — mass balance summary with fields: `total_inflow_m3`, `total_outflow_m3`, `final_volume_m3`, `mass_error_m3`, `mass_error_pct`, `steps`

**Test scenario:** Symmetric V-shaped valley (21x15, 20 m cells) with constant 15 m^3/s point-source inflow near the north end, free outflow at the south boundary, Manning's n = 0.035, 1800 s simulation.

**Success criteria** — all must hold simultaneously:

1. Project builds and solver exits with code 0
2. All final water depths >= 0
3. Maximum depth in (0.1, 5.0) m
4. Mass conservation error < 2% of total inflow
5. Total outflow at the south boundary > 0
6. Water surface elevation decreases monotonically from upstream to downstream gauge
7. Final depth profile symmetric about the valley centreline (mirrored-column RMSE < 0.02 m)
8. Downstream gauge depth converges to near-steady state in the final output intervals
9. Total outflow exceeds 50% of total inflow
10. Water arrives at the upstream gauge before the downstream gauge
11. Simulation completes within a physically reasonable number of timesteps (between 100 and 100,000)
