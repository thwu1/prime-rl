
"""End-to-end IMU preintegration pipeline for both CPI models."""

import csv
import json
import os
import numpy as np
from cpi_preintegration import CpiV1, CpiV2


def make_result(cpi):
    return {
        'DT': float(cpi.DT),
        'alpha_tau': cpi.alpha_tau.tolist(),
        'beta_tau': cpi.beta_tau.tolist(),
        'q_k2tau': cpi.q_k2tau.tolist(),
        'P_meas_trace': float(np.trace(cpi.P_meas)),
        'P_meas_diag': np.diag(cpi.P_meas).tolist(),
    }


def main():
    with open('/app/data/sensor_config.json') as f:
        config = json.load(f)

    imu_rows = []
    with open('/app/data/imu_sequence.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            imu_rows.append(row)

    noise = config['noise_parameters']
    sigma_w = noise['gyroscope_noise_density']
    sigma_wb = noise['gyroscope_random_walk']
    sigma_a = noise['accelerometer_noise_density']
    sigma_ab = noise['accelerometer_random_walk']
    imu_avg = config['options'].get('imu_averaging', False)

    bias = config['bias_linearization']
    b_w = np.array(bias['gyroscope'], dtype=float)
    b_a = np.array(bias['accelerometer'], dtype=float)

    orient = config['orientation_linearization']
    q_k_lin = np.array(orient['q_k_lin'], dtype=float)
    grav = np.array(orient['gravity'], dtype=float)

    # Model 1
    cpi_v1 = CpiV1(sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg=imu_avg)
    cpi_v1.set_linearization_points(b_w, b_a)

    # Model 2
    cpi_v2 = CpiV2(sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg=imu_avg)
    cpi_v2.set_linearization_points(b_w, b_a, q_k_lin, grav)

    for i in range(len(imu_rows) - 1):
        t0 = int(imu_rows[i]['timestamp_ns']) * 1e-9
        t1 = int(imu_rows[i + 1]['timestamp_ns']) * 1e-9
        w0 = np.array([float(imu_rows[i]['gyro_x']),
                       float(imu_rows[i]['gyro_y']),
                       float(imu_rows[i]['gyro_z'])])
        a0 = np.array([float(imu_rows[i]['accel_x']),
                       float(imu_rows[i]['accel_y']),
                       float(imu_rows[i]['accel_z'])])
        cpi_v1.feed_imu(t0, t1, w0, a0)
        cpi_v2.feed_imu(t0, t1, w0, a0)

    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/preintegrated_v1.json', 'w') as f:
        json.dump(make_result(cpi_v1), f, indent=2)

    with open('/app/output/preintegrated_v2.json', 'w') as f:
        json.dump(make_result(cpi_v2), f, indent=2)


if __name__ == '__main__':
    main()
