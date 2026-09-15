#!/usr/bin/env python3
"""Generate sensor data for localization task (stdlib only, no numpy)."""

import math
import random
import json
import os
import sqlite3


def normalize_angle(a):
    """Normalize angle to [-pi, pi)."""
    return (a + math.pi) % (2 * math.pi) - math.pi


def main():
    random.seed(42)

    # Vehicle parameters
    L = 2.5  # wheelbase [m]
    sensor_offset_x = 0.5  # sensor offset in body frame [m]
    sensor_offset_y = 0.1
    dt = 0.1  # timestep [s]
    N = 500   # number of timesteps

    # Noise parameters
    sigma_v = 0.1       # velocity noise std [m/s]
    sigma_delta = 0.01  # steering noise std [rad]
    sigma_range_base = 0.2   # base range noise std [m]
    sigma_range_scale = 0.02 # range noise scales with distance
    sigma_bearing = 0.05     # bearing noise std [rad]
    outlier_prob = 0.05      # probability of outlier observation
    max_range = 15.0         # maximum sensor range [m]

    # Systematic range biases on compromised landmarks (NOT stored in config).
    # These simulate physical tampering of landmark transponders causing
    # systematic range overestimation.
    compromised_biases = {4: 1.0, 9: 0.8}

    # Landmark positions — distributed to follow the vehicle trajectory
    # which curves from (0,0) rightward and upward to ~(88,51).
    landmarks = [
        (0,   5.0,  -3.0),
        (1,   8.0,  12.0),
        (2,  18.0,   2.0),
        (3,  22.0,  17.0),
        (4,  35.0,  10.0),
        (5,  35.0,  25.0),
        (6,  48.0,  22.0),
        (7,  48.0,  37.0),
        (8,  62.0,  32.0),
        (9,  62.0,  47.0),
        (10, 78.0,  42.0),
        (11, 82.0,  56.0),
    ]

    # ---- Generate ground truth trajectory (deterministic) ----
    true_x = [0.0] * (N + 1)
    true_y = [0.0] * (N + 1)
    true_theta = [0.0] * (N + 1)

    controls_data = []

    for k in range(N):
        t = k * dt
        v_true = 2.0 + 0.5 * math.sin(0.2 * t)
        delta_true = 0.05 * math.sin(0.1 * t + 0.3) + 0.03 * math.cos(0.2 * t)

        # Noisy controls (what the agent sees)
        v_noisy = v_true + random.gauss(0, sigma_v)
        delta_noisy = delta_true + random.gauss(0, sigma_delta)
        controls_data.append((k, v_noisy, delta_noisy))

        # Propagate true state with true controls
        x, y, theta = true_x[k], true_y[k], true_theta[k]
        true_x[k + 1] = x + v_true * math.cos(theta) * dt
        true_y[k + 1] = y + v_true * math.sin(theta) * dt
        true_theta[k + 1] = normalize_angle(
            theta + (v_true / L) * math.tan(delta_true) * dt
        )

    # ---- Generate observations ----
    obs_data = []
    for k in range(N + 1):
        x, y, theta = true_x[k], true_y[k], true_theta[k]
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        # Sensor position in world frame
        sx = x + sensor_offset_x * cos_t - sensor_offset_y * sin_t
        sy = y + sensor_offset_x * sin_t + sensor_offset_y * cos_t

        for j, lm_x, lm_y in landmarks:
            dx = lm_x - sx
            dy = lm_y - sy
            true_range = math.sqrt(dx * dx + dy * dy)
            true_bearing = normalize_angle(math.atan2(dy, dx) - theta)

            if true_range <= max_range:
                if random.random() < outlier_prob:
                    # Outlier: random range and bearing
                    obs_range = random.uniform(1.0, max_range)
                    obs_bearing = random.uniform(-math.pi, math.pi)
                else:
                    # Normal observation with heteroscedastic noise
                    range_sigma = sigma_range_base + sigma_range_scale * true_range
                    # Add systematic bias for compromised landmarks
                    range_bias = compromised_biases.get(j, 0.0)
                    obs_range = true_range + range_bias + random.gauss(0, range_sigma)
                    obs_bearing = normalize_angle(
                        true_bearing + random.gauss(0, sigma_bearing)
                    )
                obs_data.append((k, j, obs_range, obs_bearing))

    # ---- Write SQLite database ----
    os.makedirs('/app', exist_ok=True)
    db_path = '/app/sensor_data.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE landmarks (
        id INTEGER PRIMARY KEY,
        x REAL NOT NULL,
        y REAL NOT NULL
    )''')
    for lm_id, lm_x, lm_y in landmarks:
        c.execute('INSERT INTO landmarks VALUES (?, ?, ?)', (lm_id, lm_x, lm_y))

    c.execute('''CREATE TABLE controls (
        timestep INTEGER PRIMARY KEY,
        velocity REAL NOT NULL,
        steering_angle REAL NOT NULL
    )''')
    for row in controls_data:
        c.execute('INSERT INTO controls VALUES (?, ?, ?)', row)

    c.execute('''CREATE TABLE observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestep INTEGER NOT NULL,
        landmark_id INTEGER NOT NULL,
        range_m REAL NOT NULL,
        bearing_rad REAL NOT NULL
    )''')
    for row in obs_data:
        c.execute('INSERT INTO observations (timestep, landmark_id, range_m, bearing_rad) VALUES (?, ?, ?, ?)', row)

    c.execute('''CREATE TABLE ground_truth (
        timestep INTEGER PRIMARY KEY,
        x REAL NOT NULL,
        y REAL NOT NULL,
        theta REAL NOT NULL
    )''')
    for k in range(N + 1):
        c.execute('INSERT INTO ground_truth VALUES (?, ?, ?, ?)',
                  (k, true_x[k], true_y[k], true_theta[k]))

    c.execute('CREATE INDEX idx_obs_timestep ON observations(timestep)')
    c.execute('CREATE INDEX idx_controls_timestep ON controls(timestep)')

    conn.commit()
    conn.close()

    # ---- Write config (no info about compromised landmarks) ----
    config = {
        'vehicle': {
            'wheelbase': L,
            'sensor_offset': [sensor_offset_x, sensor_offset_y]
        },
        'dt': dt,
        'num_timesteps': N,
        'noise': {
            'process': {
                'sigma_v': sigma_v,
                'sigma_delta': sigma_delta
            },
            'measurement': {
                'sigma_range_base': sigma_range_base,
                'sigma_range_scale': sigma_range_scale,
                'sigma_bearing': sigma_bearing
            }
        },
        'filter': {
            'mahalanobis_gate': 9.21,
            'initial_state': [0.1, -0.05, 0.02],
            'initial_covariance': [0.1, 0.1, 0.05]
        }
    }
    with open('/app/config.json', 'w') as f:
        json.dump(config, f, indent=2)

    os.makedirs('/app/output', exist_ok=True)

    print(f"Generated {N} timesteps, {len(obs_data)} observations")
    print(f"Database: {db_path}")
    print(f"Final true state: ({true_x[-1]:.2f}, {true_y[-1]:.2f}, "
          f"{true_theta[-1]:.4f})")


if __name__ == '__main__':
    main()
