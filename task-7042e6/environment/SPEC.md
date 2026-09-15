# Output Format Specification

## `/app/fused.bp`

An ADIOS2 BP5 file with one step per velocity-sensor timestep.

### Variables (per step)

| Variable | Type | Shape |
|---|---|---|
| `velocity/Ux` | double | [Nx, Ny] |
| `velocity/Uy` | double | [Nx, Ny] |
| `temperature` | double | [Nx, Ny] |
| `pressure` | double | [Nx, Ny] |
| `derived/vorticity` | double | [Nx, Ny] |
| `derived/kinetic_energy` | double | [Nx, Ny] |
| `derived/speed` | double | [Nx, Ny] |
| `physical_time` | double | scalar |

[Nx, Ny] matches the velocity sensor's grid dimensions.

### Required Attributes (written at first step)

- `velocity/Ux/unit` = `"m/s"`
- `velocity/Uy/unit` = `"m/s"`
- `temperature/unit` = `"K"`
- `pressure/unit` = `"Pa"`
- `Nx` (int64) — grid x-dimension
- `Ny` (int64) — grid y-dimension

## `/app/results/fusion_report.json`

    {
      "output_grid": [Nx, Ny],
      "num_fused_steps": <int>,
      "source_sensors": ["sensor_velocity", "sensor_temperature", "sensor_pressure"],
      "anomaly_threshold": <float>,
      "anomalous_steps": [<0-based step indices where temperature anomaly detected>],
      "per_step_stats": [
        {
          "step": <int>,
          "time": <float, rounded to 6 decimal places>,
          "max_speed": <float, rounded to 6 decimal places>,
          "max_speed_location": [i, j],
          "mean_temperature": <float, rounded to 6 decimal places>,
          "mean_pressure": <float, rounded to 6 decimal places>,
          "max_abs_vorticity": <float, rounded to 6 decimal places>,
          "temperature_anomaly_detected": <bool>
        }
      ]
    }

One entry per fused timestep in `per_step_stats`, ordered by step index.
