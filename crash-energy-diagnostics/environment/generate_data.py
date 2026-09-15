#!/usr/bin/env python3
"""Generate synthetic crash simulation time-history data for OpenRadioss post-processing task."""

import math
import random
import json
import os


def main():
    random.seed(42)
    os.makedirs('/sim_output', exist_ok=True)

    E0 = 125000.0       # Initial kinetic energy (J): 1300 kg vehicle at ~50 km/h
    mass = 1300.0        # Vehicle mass (kg)
    v0 = math.sqrt(2 * E0 / mass)
    crash_duration = 0.080  # 80 ms

    # ========== Energy Time History ==========
    # 1001 points, 0 to 100 ms, dt = 0.1 ms
    dt_e = 0.0001
    n_e = 1001

    with open('/sim_output/energy_th.csv', 'w') as f:
        f.write('# OpenRadioss Time History Output\n')
        f.write('# Simulation: Frontal Crash 50km/h\n')
        f.write('# Time(s)  KineticE(J)  InternalE(J)  ContactE(J)  HourglassE(J)  DampingE(J)\n')

        for i in range(n_e):
            t = i * dt_e

            # Kinetic energy: half-cosine-squared decay
            if t <= crash_duration:
                ke = E0 * math.cos(math.pi * t / (2 * crash_duration)) ** 2
            else:
                ke = 0.0

            # Contact energy: oscillating with envelope build-up / decay
            if t < 0.02:
                env = t / 0.02
            elif t < 0.07:
                env = 1.0
            elif t < 0.09:
                env = (0.09 - t) / 0.02
            else:
                env = 0.0
            contact_e = 250.0 * env * math.sin(2.0 * math.pi * 45.0 * t) ** 2

            # Hourglass energy: normal quadratic + anomalous growth after t = 50 ms
            hg_norm = 40.0 * (t / 0.1) ** 2
            if t > 0.05:
                hg_anom = 8000.0 * ((t - 0.05) / 0.05) ** 2
            else:
                hg_anom = 0.0
            hg_e = hg_norm + hg_anom

            # Damping energy: linear growth
            damping_e = 80.0 * t / 0.1

            # Internal energy: computed as balance with normal HG
            # This means total = E0 + hg_anom, creating a controlled energy error
            ie = E0 - ke - contact_e - hg_norm - damping_e

            f.write(
                f'{t:.6e}  {ke:.6e}  {ie:.6e}  {contact_e:.6e}  {hg_e:.6e}  {damping_e:.6e}\n'
            )

    # ========== Acceleration Time History ==========
    # 2001 points, 0 to 100 ms, dt = 0.05 ms (fs = 20 kHz)
    dt_a = 0.00005
    n_a = 2001
    fs = 1.0 / dt_a
    g = 9.81

    with open('/sim_output/accel_node42_th.csv', 'w') as f:
        f.write('# OpenRadioss Time History Output\n')
        f.write('# Node: 42 (Head CG equivalent)\n')
        f.write('# Time(s)  AccelX(m/s2)  AccelY(m/s2)  AccelZ(m/s2)\n')

        for i in range(n_a):
            t = i * dt_a

            # Base half-sine crash pulse in X direction
            if t <= crash_duration:
                ax_base = -45.0 * g * math.sin(math.pi * t / crash_duration)
            else:
                ax_base = 0.0

            # High-frequency measurement noise
            ax_noise = random.gauss(0, 3.0 * g)

            # Contact instability spike at t = 45 ms (Gaussian, ~0.5 ms FWHM)
            spike_center = 0.045
            spike_sigma = 0.0005 / 3.0
            exponent = -((t - spike_center) / spike_sigma) ** 2
            ax_spike = -35.0 * g * math.exp(exponent) if exponent > -500 else 0.0

            ax = ax_base + ax_noise + ax_spike

            # Lateral and vertical: noise only
            ay = random.gauss(0, 1.5 * g)
            az = random.gauss(0, 1.0 * g)

            f.write(f'{t:.6e}  {ax:.6e}  {ay:.6e}  {az:.6e}\n')

    # ========== Metadata ==========
    metadata = {
        'simulation': 'Frontal Crash 50km/h',
        'solver': 'OpenRadioss',
        'vehicle_mass_kg': mass,
        'initial_velocity_ms': round(v0, 4),
        'initial_kinetic_energy_J': E0,
        'crash_duration_s': crash_duration,
        'energy_dt_s': dt_e,
        'accel_dt_s': dt_a,
        'accel_sampling_rate_Hz': fs,
        'accel_node': 42,
        'accel_units': 'm/s2',
        'energy_units': 'J',
    }

    with open('/sim_output/metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    print('Data generation complete.')
    print(f'  Energy TH: {n_e} timesteps, dt = {dt_e * 1000} ms')
    print(f'  Accel TH:  {n_a} timesteps, dt = {dt_a * 1000} ms, fs = {fs} Hz')


if __name__ == '__main__':
    main()
