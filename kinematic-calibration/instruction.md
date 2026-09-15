A 6-DOF robot arm's nominal kinematic model is in `/app/robot.urdf`. Manufacturing tolerances cause the physical robot's joint origins to deviate from nominal values. `/app/measurements.json` contains 200 joint-angle / end-effector-position pairs recorded from the real robot.

Identify per-joint corrections to the `origin xyz` translation parameters (3 per joint, 18 total) that minimize discrepancy between nominal FK predictions and measured positions.

FK convention per joint: translate by `origin xyz`, rotate by `origin rpy` (Rz-Ry-Rx), rotate around `axis` by the joint angle. A tool-tip offset `[0.08, 0.0, 0.0]` is appended after all joints. Measurement noise is ~0.5 mm; true perturbations are 1-5 mm per axis.

Write `/app/calibration_result.json`:

```json
{
  "nominal_rms_error_m": <float>,
  "calibrated_rms_error_m": <float>,
  "parameter_corrections": {
    "joint1": {"dx": <float>, "dy": <float>, "dz": <float>},
    "joint6": {"dx": <float>, "dy": <float>, "dz": <float>}
  },
  "validation_predictions": [[x, y, z], ...]
}
```

`validation_predictions`: FK predictions from your calibrated model for each configuration in `/app/validation_configs.json`, in order.