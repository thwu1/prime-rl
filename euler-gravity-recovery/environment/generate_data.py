#!/usr/bin/env python3
"""Generate synthetic gravity survey data with TOML config and field notes."""

import csv
import math
import os
import random

G = 6.674e-11  # gravitational constant, m^3/(kg*s^2)

X_MIN, X_MAX = -50000, 50000
Y_MIN, Y_MAX = -50000, 50000
SPACING = 1000
OBS_HEIGHT = 0.0

# Five buried point-mass sources at various positions and depths
SOURCES = [
    (15000.0, 20000.0, -8000.0, 5e13),
    (-25000.0, -15000.0, -5000.0, 2e13),
    (30000.0, -30000.0, -12000.0, 3e14),
    (-10000.0, 35000.0, -3500.0, 1e13),
    (-35000.0, 5000.0, -6000.0, 4e13),
]

NOISE_STD = 0.05  # mGal


def main():
    random.seed(42)

    eastings = list(range(X_MIN, X_MAX + 1, SPACING))
    northings = list(range(Y_MIN, Y_MAX + 1, SPACING))

    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/results', exist_ok=True)

    # Write gravity CSV
    with open('/app/data/gravity_data.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['easting', 'northing', 'g_z'])
        for ni in northings:
            for ei in eastings:
                gz = 0.0
                for e0, n0, u0, mass in SOURCES:
                    dx = ei - e0
                    dy = ni - n0
                    dz = OBS_HEIGHT - u0
                    r = math.sqrt(dx * dx + dy * dy + dz * dz)
                    gz += G * mass * dz / (r * r * r)
                gz *= 1e5  # convert to mGal
                # Add polynomial regional trend
                gz += 2.0 + 3e-5 * ei - 2e-5 * ni + 5e-11 * ei * ei
                # Add Gaussian measurement noise
                gz += random.gauss(0, NOISE_STD)
                writer.writerow([f'{ei:.1f}', f'{ni:.1f}', f'{gz:.6f}'])

    # Write TOML survey configuration (deliberately incomplete - no structural
    # index, no noise level, no source count)
    toml_content = """# Gravity survey configuration

[survey]
region = [{xmin}, {xmax}, {ymin}, {ymax}]
grid_spacing_m = {spacing}
n_eastings = {ne}
n_northings = {nn}

[instrument]
type = "relative_gravimeter"
measurement = "vertical_gravitational_acceleration"
units = "mGal"
drift_corrected = true

[processing]
tide_corrected = true
terrain_correction = "not_applied"
regional_field_removed = false
""".format(
        xmin=X_MIN, xmax=X_MAX, ymin=Y_MIN, ymax=Y_MAX,
        spacing=SPACING, ne=len(eastings), nn=len(northings),
    )
    with open('/app/data/survey_config.toml', 'w') as f:
        f.write(toml_content)

    # Write field notes giving geological context without technical hints
    field_notes = """Survey Field Notes
==================
Area: 100 km x 100 km test range, flat terrain, elevation ~0 m ASL.
Acquisition: East-west survey lines, 1 km station spacing.
Instrument: LaCoste & Romberg relative gravimeter, base-station tied.
Conditions: Calm weather, minimal vibration. Some cultural noise near
    the NE sector from nearby road construction.

Geological context: The survey area overlies a sedimentary basin with
    several known mineral prospects at varying depths. Previous magnetic
    surveys suggested discrete compact bodies rather than extended sheet-
    like structures. No prior gravity work has been done in this area.

Data quality: Standard drift and tide corrections applied in the field.
    No Bouguer or terrain corrections performed (flat area, minimal
    topographic relief). Regional geological gradient is present in the
    raw data and has NOT been removed.
"""
    with open('/app/data/field_notes.txt', 'w') as f:
        f.write(field_notes)

    print("Gravity survey data generated successfully.")


if __name__ == '__main__':
    main()
