An ARIAC-style inspection conveyor scans twelve 18650 battery cells using three LIDAR sensors (A, B, C) positioned at 120° intervals. Each sensor covers approximately 240° of the cell circumference, creating pairwise overlapping views. Sensors differ in noise characteristics (Grade A lowest, Grade C highest) and each carries an unknown systematic translational calibration bias in XY that is constant across all cells.

Scan data: `/app/scans/cell_XX_Y.npz` (XX = cell ID 00–11, Y = sensor letter A/B/C; NumPy `.npz`, array key `points`, shape `(N,3)` in meters). Sensor and cell specifications: `/app/sensor_config.yaml`.

Each cell is a cylinder (axis along Z, XY center offset slightly from origin). Every cell has a manufacturing seam line — a narrow outward ridge running the full cell height — that is a normal manufacturing artifact, not a defect. Some cells carry one or more physical defects deviating at least 2mm from the nominal cylindrical surface:

- **DENT** (type 1): roughly circular inward depression
- **BULGE** (type 2): roughly circular outward protrusion
- **SCRATCH** (type 3): narrow elongated inward depression along the cell height

Build a pipeline that estimates relative sensor calibration biases from overlapping observations, fuses multi-sensor data, discriminates manufacturing seam artifacts from defects, and detects and classifies all defects on each cell. Write results to `/app/inspection_results.json`:

```json
{
  "sensor_calibration": {
    "bias_B_minus_A": {"dx": <float>, "dy": <float>},
    "bias_C_minus_A": {"dx": <float>, "dy": <float>}
  },
  "cells": [
    {"cell_id": 0, "passed": true, "defects": []},
    {"cell_id": 4, "passed": false, "defects": [
      {"defect_type": 1, "theta": 1.234, "z": 0.032}
    ]}
  ]
}
```

`sensor_calibration`: estimated translational biases of sensors B and C relative to sensor A (meters). `cell_id`: integer 0–11. `passed`: true if no defects found. `defect_type`: 1=DENT, 2=BULGE, 3=SCRATCH. `theta`: azimuthal angle in radians in [−π, π] of defect centroid measured from +X, positive counterclockwise viewed from +Z (right-hand rule). `z`: height in meters of defect centroid from cell bottom.