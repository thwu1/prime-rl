An ArduPilot quadcopter experienced degraded navigation during a flight. The vehicle ran EKF3 with two filter cores (core 0 using IMU0/Compass0, core 1 using IMU1/Compass1). An automatic EKF lane switch occurred mid-flight. The raw binary DataFlash flight log is at `/app/flight_log/flight.bin` in ArduPilot's native `.bin` format. A parameter reference is at `/app/param_reference.txt`.

The log contains interleaved binary messages at different rates:
- `PARM` — vehicle parameter values
- `GPS` — GPS fix status (field `Status`: 3 = 3D fix, 0 = no fix)
- `XKF1` / `XKF4` — per-core velocity/position innovations and their reported variances
- `XKF2` / `XKF5` — per-core magnetometer/yaw innovations and their reported variances
- `CTUN` — altitude telemetry
- `STAT` — which EKF core is currently the primary navigator (`MainCoreId`)
- `MSG` — free-text event messages

Each EKF message has a core index field `C`. The EKF noise parameters (`EK3_*_NOISE`) are shared globally across cores. Innovation field names use ArduPilot log conventions (e.g., `IVN` for velocity-north innovation). The corresponding variance fields use a different prefix. The mapping between innovation fields and noise parameters must be determined from the data and the parameter reference.

Analyze the flight to calibrate the EKF noise parameters. The calibration must use innovation data ONLY from whichever core was primary at each point in time, and ONLY during stable cruise flight — excluding ground operations, takeoff/landing transients, sensor outage periods, and anomalous intervals. Some noise parameters are shared across multiple channels and must be jointly estimated.

Write `/app/output/analysis_results.json`:

```json
{
  "corrected_params": {
    "EK3_VELNE_NOISE": <float>,
    "EK3_VELD_NOISE": <float>,
    "EK3_POSNE_NOISE": <float>,
    "EK3_ALT_NOISE": <float>,
    "EK3_MAG_NOISE": <float>,
    "EK3_YAW_NOISE": <float>
  },
  "inconsistent_channels": ["<channel_name>", ...],
  "primary_core_switches": [
    {"sample_index": <int>, "from_core": <int>, "to_core": <int>}
  ],
  "cruise_phase": {"start_sample": <int>, "end_sample": <int>},
  "gps_outage": {"detected": <bool>, "start_index": <int>, "end_index": <int>},
  "anomalies": [{"channel": <str>, "type": <str>, "description": <str>}]
}
```

Channel names in `inconsistent_channels` must use the parameter-reference names (e.g., `VelN`, not `IVN`). Sample indices refer to the sequential position in the per-core XKF message stream (0-based).