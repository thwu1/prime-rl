PVS formal specifications in `/app/specs/` define the WCV_TAUMOD (Well-Clear Volume with Tau-Modified time variable) conflict detection algorithm — the core of RTCA DO-365 MOPS for UAS detect-and-avoid. These specifications are machine-checked proofs of correctness for the algorithm used in NASA's DAIDALUS reference implementation.

Encounter scenarios in `/app/data/encounters/` describe aircraft proximity situations as JSON files with ownship and intruder states (Euclidean coordinates, track/groundspeed/vertical-speed). WCV parameter configurations in `/app/data/configs/` specify detection thresholds. Coordinate conventions and unit definitions are in `/app/data/format.md`.

Implement the complete WCV_TAUMOD conflict detection pipeline as a Python module at `/app/wcv_taumod.py`. The module must expose these functions with exact signatures:

- `horizontal_wcv_taumod_interval(T, s, v, TAUMOD, DTHR)` — returns `(entry, exit)` tuple; `s` and `v` are 2-tuples `(x,y)` in nmi and nmi/s; empty interval represented as `entry > exit`
- `vertical_wcv_interval(B, T, sz, vz, TCOA, ZTHR)` — `sz` in ft, `vz` in ft/s; returns `(entry, exit)`
- `wcv_taumod_interval(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR)` — `s3`/`v3` are 3-tuples `(x, y, z)` with horizontal nmi/nmi/s, vertical ft/ft/s; returns `(entry, exit)`
- `wcv_taumod_detection(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR)` — returns `bool`

Then process all encounter/config pairs and write `/app/output/results.json`:

```json
{
  "results": [
    {
      "encounter": "<encounter_name>",
      "intruder": "<intruder_id>",
      "config": "<config_name>",
      "conflict": true,
      "entry_time_s": 36.3,
      "exit_time_s": 76.8
    }
  ]
}
```

Set `entry_time_s` and `exit_time_s` to `null` when `conflict` is `false`.

The implementation must faithfully translate the PVS formal specifications — the quadratic-formula interval computation in `horizontal_WCV_taumod_interval`, the altitude-crossing logic in `vertical_WCV_interval`, and the 3D composition in `WCV_interval`. Do not approximate with simulation or sampling.