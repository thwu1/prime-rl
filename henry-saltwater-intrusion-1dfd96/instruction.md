`/app/build_model.py` constructs a MODFLOW 6 coupled groundwater-flow and solute-transport simulation for a density-dependent saltwater intrusion scenario, reading physical parameters from `/app/parameters.json`. The script contains multiple defects that cause runtime failures or physically incorrect output. `/app/postprocess.py` converts simulation output to the required format but depends on a correct simulation run.

The `mf6` executable is not pre-installed. Python scientific packages are not pre-installed.

Produce `/app/results.json`:

```json
{
  "bottom_concentrations": [<20 floats>],
  "toe_position": <float>,
  "mixing_zone_width": <float>
}
```

- `bottom_concentrations`: steady-state solute concentrations (g/L) in the bottom model layer, ordered inland to sea.
- `toe_position`: x-coordinate (m from left boundary) where bottom-layer concentration equals half the seawater concentration, by linear interpolation between adjacent cell centers.
- `mixing_zone_width`: horizontal distance (m) between the 10% and 90% seawater-concentration isochlors in the bottom layer, each by linear interpolation.

The model workspace must be `/app/model/`. Success criteria:

- `/app/model/` contains `mfsim.nam` and converged output files (`.hds`, `.ucn`).
- Bottom-layer concentrations increase monotonically (inland to sea) and stay within [0, seawater concentration].
- Reported concentrations in `/app/results.json` are consistent with actual `.ucn` model output.
- Results match the physically correct steady-state solution for the given parameters.
