Data files at `/app/data/` model a radiotherapy treatment scenario with dose distributions, anatomical structures, and a clinical protocol. Generate them by running `python3 /opt/generate_data.py`.

Implement `/app/rt_analysis.py` exposing a callable `main()` that reads the generated data and writes `/app/results/analysis.json`. All output dose values must be in Gray (Gy) regardless of input file conventions.

Output schema:

```json
{
  "structures": {
    "PTV": {"volume_cm3": float, "D95_gy": float, "Dmean_gy": float, "Dmax_gy": float},
    "Heart": {"volume_cm3": float, "Dmean_gy": float, "Dmax_gy": float, "V30_gy_pct": float},
    "SpinalCord": {"volume_cm3": float, "Dmax_gy": float, "D0_1cc_gy": float}
  },
  "dose_summation": {"max_dose_gy": float, "mean_dose_gy": float},
  "gamma": {"pass_rate_pct": float, "mean_gamma": float, "max_gamma": float, "evaluated_points": int},
  "protocol_compliance": {
    "PTV_D95": bool, "Heart_Dmean": bool, "Heart_V30": bool,
    "SpinalCord_Dmax": bool, "SpinalCord_D0_1cc": bool,
    "overall_pass": bool, "max_boost_factor": float
  }
}
```

The data directory contains three dose grids (`dose_primary.json`, `dose_secondary.json`, `dose_boost.json`), anatomical structure contours (`structures.json`), and a clinical protocol (`protocol.json`). Inspect each file to determine its schema and units.

**Structure metrics**: Compute standard dose-volume histogram statistics for each structure defined in `structures.json`, evaluated against the primary dose distribution. Structure contour geometry and dose grid metadata in the data files fully specify how voxel membership and volumes are determined.

**Dose summation**: Report the max and mean dose of the combined primary + secondary distributions, evaluated on the primary grid's coordinate system. The secondary grid differs in spacing, origin, and extent.

**Gamma index**: Perform a 3D gamma analysis comparing primary versus secondary distributions using the criteria specified in `protocol.json`. Report pass rate (percentage with gamma <= 1), mean gamma, max gamma, and number of evaluated points.

**Protocol compliance**: Evaluate each constraint from `protocol.json` against the primary dose. `overall_pass` is `true` only if every constraint is satisfied. `max_boost_factor` is the largest non-negative scalar such that adding that scaled boost distribution to the primary dose still satisfies all organ-at-risk constraints simultaneously. Report `0.0` if no positive scaling is feasible.
