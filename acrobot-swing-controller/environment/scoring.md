# RealAI Score

The RealAI Score evaluates controller performance using multiple criteria:

## Criteria

1. **Swingup Success** (c_success): Binary. 1 if the end-effector is above h=0.45 m at the end of simulation and stays above continuously from the time it first crosses the threshold; 0 otherwise.

2. **Swingup Time** (c_time): The time [s] when the end-effector first enters the goal region (y_ee >= 0.45 m) and does not leave until the end.

3. **Energy** (c_energy): Mechanical energy used during execution [J]. Computed as the integral of |u^T * qdot| over the simulation duration.

4. **Torque Cost** (c_tau_cost): Quadratic torque cost [N^2 m^2]. Computed as the integral of u^T * R * u with R = identity.

5. **Torque Smoothness** (c_tau_smooth): Standard deviation of the changes in the torque signal [Nm].

6. **Velocity Cost** (c_vel_cost): Quadratic velocity cost [rad^2/s^2]. Computed as the integral of qdot^T * Q * qdot with Q = identity.

## Score Formula

    S = c_success * (1 - (1/5) * sum_{i} tanh(c_i / n_i))

where the sum is over the five sub-criteria (time, energy, torque cost, torque smoothness, velocity cost).

## Normalization Coefficients

| Criterion         | Normalization n |
|--------------------|-----------------|
| Swingup Time       | 20.0            |
| Energy             | 60.0            |
| Torque Cost        | 20.0            |
| Torque Smoothness  | 0.1             |
| Velocity Cost      | 400.0           |

A higher score is better. Maximum possible is 1.0 (instant swing-up with zero cost).
