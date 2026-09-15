# DriveActuator Dynamics — Reference Pipeline Specification

## Overview

The DriveActuator models velocity-controlled drive actuators (e.g., wheel motors on a mobile robot). It processes a commanded velocity through a pipeline of four stages in **strict sequential order**, where each stage's output becomes the next stage's input.

All four parameters are strictly positive real numbers.

## Pipeline Stages (Reference Ordering)

The actuator processes each sample at an internal simulation rate of **1000 Hz** (dt = 0.001 s). The four stages, applied **in the reference order**, are:

### Stage 1: Dead Time Delay

A pure transport delay. The input signal is delayed by `dead_time` seconds before any processing occurs. This models communication latency, processing delays, and motor controller response time.

**Implementation**: Maintain a circular FIFO buffer of length `round(dead_time / dt) + 1`. At each timestep, write the current input to the buffer and read the value from `round(dead_time / dt)` steps ago. Buffer is initialized to all zeros.

**Parameter**: `dead_time` [seconds]

### Stage 2: Velocity Saturation

Hard clamp of the delayed signal to the symmetric range `[-max_velocity, +max_velocity]`.

**Parameter**: `max_velocity` [m/s]

### Stage 3: First-Order Low-Pass Filter

Discrete first-order IIR filter that models the motor controller's proportional-integral response. Applied as exponential smoothing:

```
alpha = dt / (time_constant + dt)
state = state + alpha * (input - state)
output = state
```

The filter state is initialized to **0.0** (actuator starts at rest).

**Parameter**: `time_constant` [seconds] — larger values produce a slower, more damped response

### Stage 4: Acceleration Limiting

Constrains the rate of change of the output velocity. If the difference between the current filter output and the previous acceleration-limited output exceeds `max_acceleration * dt`, the change is clamped:

```
max_change = max_acceleration * dt
diff = filter_output - previous_accel_output
if diff > max_change:
    output = previous_accel_output + max_change
elif diff < -max_change:
    output = previous_accel_output - max_change
else:
    output = filter_output
```

The acceleration-limited output state is initialized to **0.0**.

**Parameter**: `max_acceleration` [m/s²]

## Parameters Summary

| Parameter          | Unit  | Description                              |
|--------------------|-------|------------------------------------------|
| `dead_time`        | s     | Transport delay before any response      |
| `time_constant`    | s     | Low-pass filter time constant            |
| `max_acceleration` | m/s²  | Maximum rate of velocity change          |
| `max_velocity`     | m/s   | Maximum absolute attainable velocity     |

## Critical Implementation Notes

1. **Pipeline order matters**: The ordering of post-saturation stages (Stages 3 and 4) significantly affects the dynamic response. Swapping the low-pass filter and acceleration limiter produces measurably different transient behavior for the same parameter values.
2. All internal state variables are initialized to **0.0** (actuator starts from rest).
3. The simulation runs at **1000 Hz** internally. Input/output data may be sampled at a lower rate (e.g., 100 Hz).
4. The dead time delay uses `round(dead_time / dt)` samples, not `floor` or `ceil`.
5. Each stage processes one sample at a time in the inner simulation loop — there is no batch processing across stages.

## Data Format

- Step response CSVs have columns: `time`, `command`, `response`
  - The command transitions from 0 to the step value at t = 0.5 seconds
  - Data is sampled at 100 Hz (every 0.01 seconds)
  - Measurements include realistic sensor noise
- Novel command CSVs have columns: `time`, `command`
  - Data is sampled at 100 Hz
- Expected output response CSVs should have columns: `time`, `response`
  - Must match the time points from the corresponding command CSV
