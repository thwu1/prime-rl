Domain data for a four-reservoir hydrologic network is in `/app/domain/`. The network forms a directed acyclic graph — the topology is encoded as a directed edge list in the parameter dataset, not a simple linear cascade.

A reference implementation module adapted from the USGS pywatershed modeling framework is at `/app/reference/reservoir_ops.py`. It depends on framework base classes not present in the environment and is not directly executable, but documents the operating rules, physical loss processes, their execution ordering, and the network routing methodology.

Simulate the full 730-day period and write daily results to `/app/results/simulation.csv` with these columns (in order):

`day`, `date`, then for each reservoir r1 through r4 (in order): `rN_inflow`, `rN_storage`, `rN_release`, `rN_spill`, `rN_outflow`, `rN_evap`, `rN_seepage`, `rN_nor_hi`, `rN_nor_lo`

Column definitions:
- `day`: 0-indexed integer day number
- `date`: YYYY-MM-DD format
- `*_inflow`: total inflow including routed upstream contributions (m³/s)
- `*_storage`: end-of-timestep storage (MCM — million cubic meters)
- `*_release`, `*_spill`, `*_outflow`: flow components (m³/s); outflow = release + spill
- `*_evap`, `*_seepage`: physical loss rates as equivalent flow (m³/s)
- `*_nor_hi`, `*_nor_lo`: seasonal operating bounds (dimensionless fractions of capacity)

The output file must contain exactly 730 data rows plus a header row.