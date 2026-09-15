# EKF3 Innovation Analysis Reference

## Innovations

In the Extended Kalman Filter, an **innovation** (or measurement residual) is the
difference between an actual sensor measurement and the filter's prediction of that
measurement based on the current state estimate:

    innovation = z_measured - z_predicted

If the filter is properly tuned, innovations should be zero-mean with a variance that
matches the filter's predicted innovation variance. Persistent non-zero mean innovations
indicate a sensor bias or model error. Innovations with variance significantly different
from the filter's prediction indicate misconfigured noise parameters.

## Innovation Variance

The filter computes a predicted innovation variance (innovation covariance for
vector measurements):

    S = H * P * H' + R

where:
- `H` is the measurement Jacobian (maps state errors to measurement errors)
- `P` is the state error covariance matrix (represents uncertainty in state estimates)
- `H * P * H'` represents the **process noise contribution** to innovation variance —
  the uncertainty propagated from the state prediction
- `R` is the **measurement noise covariance** — for scalar measurements, `R = σ_noise²`
  where `σ_noise` is the configured noise parameter

The key relationship is that the reported innovation variance `S` is the sum of two
independent contributions: one from process/prediction uncertainty (`H*P*H'`) and one
from measurement noise (`R`). The noise parameters directly control `R`.

## Normalized Innovation Squared (NIS)

The NIS is the fundamental diagnostic metric for EKF consistency:

    NIS = innovation² / S

For a properly tuned filter with Gaussian assumptions:
- **E[NIS] = 1** — the expected value of NIS equals 1 (chi-squared with 1 DOF)
- The NIS sequence should be white (uncorrelated over time)

**Interpretation:**
- **mean(NIS) >> 1**: The noise parameter `σ_noise` is set too low. The filter is
  overconfident — it under-predicts innovation variance, causing measurements to be
  partially or fully rejected. Navigation accuracy degrades.
- **mean(NIS) << 1**: The noise parameter `σ_noise` is set too high. The filter trusts
  measurements excessively, which can cause noisy state estimates.
- **mean(NIS) ≈ 1**: The filter is properly tuned for this measurement channel.

## Innovation Gate Parameters

ArduPilot uses gate parameters (`EK3_*_GATE`) expressed as a percentage of the
standard deviation. A gate of 500 means the filter accepts measurements up to 5σ
from the prediction:

    acceptance test: |innovation| / sqrt(S) < gate / 100

Measurements exceeding the gate are rejected entirely.

## ArduPilot EKF3 Noise Parameters

Each noise parameter controls the measurement noise variance `R = σ²` for one or more
measurement channels:

| Parameter | Channels | Unit | Valid Range | Description |
|-----------|----------|------|-------------|-------------|
| `EK3_VELNE_NOISE` | VelN, VelE | m/s | [0.05, 5.0] | GPS horizontal velocity noise |
| `EK3_VELD_NOISE` | VelD | m/s | [0.05, 5.0] | GPS vertical velocity noise |
| `EK3_POSNE_NOISE` | PosN, PosE | m | [0.1, 10.0] | GPS horizontal position noise |
| `EK3_ALT_NOISE` | Alt | m | [0.1, 10.0] | Barometric altitude noise |
| `EK3_MAG_NOISE` | MagX, MagY, MagZ | Gauss | [0.01, 0.5] | Magnetometer noise |
| `EK3_YAW_NOISE` | Yaw | rad | [0.01, 1.0] | Yaw angle noise |

**Shared parameters:** Several parameters control multiple channels simultaneously.
For example, `EK3_VELNE_NOISE` sets the noise for both VelN and VelE. When
calibrating shared parameters, information from all associated channels should be
used to produce a single optimal value.

Note that each channel may have a **different process noise contribution** (`H*P*H'`)
even when they share the same measurement noise parameter.

## Data Files

- `innovations.csv`: Time-indexed innovation values. Columns: `TimeUS` (microseconds
  since boot), followed by channel names (`VelN`, `VelE`, `VelD`, `PosN`, `PosE`,
  `Alt`, `MagX`, `MagY`, `MagZ`, `Yaw`). Values are the raw innovation in the
  channel's native unit.

- `variances.csv`: Same column structure as innovations. Contains the **reported
  innovation variance** `S` for each channel at each time step. This is what the
  EKF computes as the expected innovation variance given current state uncertainty
  and configured noise parameters.

- `params.txt`: Current parameter values in comma-separated format: `PARAM_NAME,value`.
  Includes both noise parameters (`EK3_*_NOISE`) and gate parameters (`EK3_*_GATE`).

## Sensor Dependencies

- **GPS channels** (`VelN`, `VelE`, `VelD`, `PosN`, `PosE`): Depend on GPS satellite
  reception. GPS signal loss causes these measurements to become unavailable.
- **Alt channel**: Uses barometric pressure sensor (independent of GPS).
- **Magnetometer channels** (`MagX`, `MagY`, `MagZ`): Use onboard electronic compass.
  Susceptible to electromagnetic interference from motors, power lines, or
  ferromagnetic materials, which can cause systematic bias offsets.
- **Yaw channel**: Uses compass-derived heading (independent of GPS).
