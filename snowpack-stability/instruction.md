Build `/app/snowpack_stability.py` — a tool that performs avalanche stability analysis on SNOWPACK `.pro` profile data, replicating the computation pipeline of the SNOWPACK model (WSL/SLF Davos). The C++ reference implementation is provided at `/app/src/` (`StabilityAlgorithms.cc`, `Stability.cc`, `Constants.h`, `DataClasses.cc`, `DataClasses.h`, `StabilityAlgorithms.h`).

**CLI:**
```
python3 /app/snowpack_stability.py <pro_file> <timestamp> --slope-angle <degrees>
```

The `.pro` file at `/app/data/profile.pro` contains layered snow profile time series (Weissfluhjoch study plot, winter 1995-96, 3 timesteps). Timestamps use the file's own format.

**Output:** JSON to stdout matching this schema:

```json
{
  "timestamp": "...",
  "n_elements": 0,
  "snow_height_cm": 0.0,
  "penetration_depth_m": 0.0,
  "profile": {
    "stability_class": 0,
    "min_Sk38": 0.0, "min_Sk38_height_cm": 0.0,
    "min_Sn38": 0.0, "min_Sn38_height_cm": 0.0,
    "min_SSI": 0.0, "min_SSI_height_cm": 0.0
  },
  "layers": [{
    "height_cm": 0.0, "density_kg_m3": 0.0, "grain_type": 0,
    "shear_strength_kPa": 0.0, "Sk38": 0.0, "Sn38": 0.0,
    "SSI": 0.0, "critical_cut_length_m": 0.0
  }]
}
```

**Requirements:**

- Use the `DEFAULT` strength model variant as configured in the C++ source.
- Compute per-layer natural stability (Sn38), skier stability (Sk38), structural stability index (SSI), and critical cut length, matching the C++ implementation's behavior.
- Use the default stability classification scheme as configured in the source.
- All stability indices clamped to [0.05, 6.0]. Critical cut length clamped to [0, 3.0] m.
- Profile-level minima must respect ground roughness and minimum slab constraints defined in the source constants.
- Stability class −1 when snowpack is too shallow for assessment.
- The tool must produce correct results across different `--slope-angle` values, which affect stress reduction and depth computations as specified in the C++ source.
