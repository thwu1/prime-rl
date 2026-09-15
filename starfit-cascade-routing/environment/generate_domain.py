#!/usr/bin/env python3
"""Generate domain files for the multi-reservoir network simulation.

Creates params.json (reservoir parameters, network topology, loss parameters)
and forcing.csv (daily inflow timeseries and PET data) in /app/domain/.
"""

import csv
import json
import math
import os


def generate():
    os.makedirs('/app/domain', exist_ok=True)

    # ── Parameter file ─────────────────────────────────────────────
    params = {
        'start_date': '2019-01-01',
        'num_days': 730,
        'dt_seconds': 86400,
        'description': (
            'Four-reservoir network domain with physical losses. '
            'Topology: R1->R3, R2->R4, R3->R4 (branching DAG). '
            'Highland (R1) cascades through Main Stem (R3); '
            'Snowfield (R2) feeds Valley (R4) directly; '
            'R3 also feeds R4 creating a confluence. '
            'Includes evaporation (power-law area-storage) and '
            'seepage (linear rate) loss parameterizations.'
        ),
        'reservoirs': [
            {
                'id': 1,
                'capacity_mcm': 800.0,
                'mean_inflow_cms': 45.0,
                'initial_storage_mcm': 550.0,
                'area_coeff': 0.12,
                'area_exp': 0.667,
                'pet_adjustment': 0.75,
                'seepage_rate': 0.0003,
                'nor_hi': {
                    'amplitude': 0.20, 'phase': 0.50, 'offset': 0.70,
                    'floor': 0.50, 'ceiling': 0.90
                },
                'nor_lo': {
                    'amplitude': 0.15, 'phase': 0.50, 'offset': 0.25,
                    'floor': 0.10, 'ceiling': 0.40
                },
                'release': {
                    'flood_max': 2.0, 'flood_scale': 3.0,
                    'flood_exp': 1.5, 'flood_base': 1.0,
                    'normal_coeff': 1.0,
                    'conserve_min': 0.5, 'conserve_scale': 2.0,
                    'conserve_exp': 2.0, 'conserve_base': 0.5
                }
            },
            {
                'id': 2,
                'capacity_mcm': 400.0,
                'mean_inflow_cms': 25.0,
                'initial_storage_mcm': 220.0,
                'area_coeff': 0.08,
                'area_exp': 0.72,
                'pet_adjustment': 0.65,
                'seepage_rate': 0.0002,
                'nor_hi': {
                    'amplitude': 0.18, 'phase': 0.80, 'offset': 0.65,
                    'floor': 0.45, 'ceiling': 0.85
                },
                'nor_lo': {
                    'amplitude': 0.10, 'phase': 0.80, 'offset': 0.20,
                    'floor': 0.08, 'ceiling': 0.32
                },
                'release': {
                    'flood_max': 1.8, 'flood_scale': 2.5,
                    'flood_exp': 1.2, 'flood_base': 0.8,
                    'normal_coeff': 0.9,
                    'conserve_min': 0.4, 'conserve_scale': 1.5,
                    'conserve_exp': 1.8, 'conserve_base': 0.4
                }
            },
            {
                'id': 3,
                'capacity_mcm': 1200.0,
                'mean_inflow_cms': 65.0,
                'initial_storage_mcm': 720.0,
                'area_coeff': 0.15,
                'area_exp': 0.65,
                'pet_adjustment': 0.90,
                'seepage_rate': 0.0004,
                'nor_hi': {
                    'amplitude': 0.22, 'phase': 0.60, 'offset': 0.68,
                    'floor': 0.48, 'ceiling': 0.88
                },
                'nor_lo': {
                    'amplitude': 0.12, 'phase': 0.60, 'offset': 0.22,
                    'floor': 0.09, 'ceiling': 0.35
                },
                'release': {
                    'flood_max': 2.2, 'flood_scale': 2.8,
                    'flood_exp': 1.4, 'flood_base': 0.9,
                    'normal_coeff': 0.95,
                    'conserve_min': 0.45, 'conserve_scale': 1.8,
                    'conserve_exp': 1.9, 'conserve_base': 0.45
                }
            },
            {
                'id': 4,
                'capacity_mcm': 600.0,
                'mean_inflow_cms': 95.0,
                'initial_storage_mcm': 330.0,
                'area_coeff': 0.10,
                'area_exp': 0.70,
                'pet_adjustment': 1.0,
                'seepage_rate': 0.0001,
                'nor_hi': {
                    'amplitude': 0.15, 'phase': 0.40, 'offset': 0.72,
                    'floor': 0.55, 'ceiling': 0.87
                },
                'nor_lo': {
                    'amplitude': 0.08, 'phase': 0.40, 'offset': 0.28,
                    'floor': 0.15, 'ceiling': 0.38
                },
                'release': {
                    'flood_max': 1.9, 'flood_scale': 3.2,
                    'flood_exp': 1.3, 'flood_base': 1.1,
                    'normal_coeff': 1.05,
                    'conserve_min': 0.55, 'conserve_scale': 2.2,
                    'conserve_exp': 2.1, 'conserve_base': 0.55
                }
            }
        ],
        'edges': [
            {'upstream': 1, 'downstream': 3},
            {'upstream': 3, 'downstream': 4},
            {'upstream': 2, 'downstream': 4}
        ]
    }

    with open('/app/domain/params.json', 'w') as f:
        json.dump(params, f, indent=2)

    # ── Forcing file ───────────────────────────────────────────────
    days = list(range(730))
    forcing_rows = []

    for d in days:
        # R1: snowmelt-driven, peak in late spring/summer
        q1 = (45.0
              + 25.0 * math.sin(2.0 * math.pi * d / 365.0 - math.pi / 2.0)
              + 8.0 * math.sin(2.0 * math.pi * d / 183.0))
        q1 = max(8.0, q1)

        # R2: snowfield, sharper peak, different phase
        q2 = (25.0
              + 18.0 * math.sin(2.0 * math.pi * d / 365.0 - math.pi / 3.0)
              + 4.0 * math.sin(2.0 * math.pi * d / 122.0))
        q2 = max(4.0, q2)

        # R3: local tributary, moderate seasonal signal
        q3 = (20.0
              + 10.0 * math.sin(2.0 * math.pi * d / 365.0 - math.pi / 4.0)
              + 3.0 * math.sin(2.0 * math.pi * d / 91.25))
        q3 = max(3.0, q3)

        # R4: valley, rain-dominated, earlier peak
        q4 = (15.0
              + 8.0 * math.sin(2.0 * math.pi * d / 365.0 + math.pi / 6.0)
              + 2.0 * math.sin(2.0 * math.pi * d / 73.0))
        q4 = max(2.0, q4)

        # PET: peaks in summer, low in winter
        p = 3.0 + 2.5 * math.sin(2.0 * math.pi * d / 365.0 - math.pi / 2.0)
        p = max(0.5, min(6.0, p))

        forcing_rows.append({
            'day': d,
            'reservoir_1_local_inflow_cms': round(q1, 6),
            'reservoir_2_local_inflow_cms': round(q2, 6),
            'reservoir_3_local_inflow_cms': round(q3, 6),
            'reservoir_4_local_inflow_cms': round(q4, 6),
            'pet_mm_per_day': round(p, 6),
        })

    with open('/app/domain/forcing.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'day', 'reservoir_1_local_inflow_cms',
            'reservoir_2_local_inflow_cms',
            'reservoir_3_local_inflow_cms',
            'reservoir_4_local_inflow_cms',
            'pet_mm_per_day'
        ])
        writer.writeheader()
        writer.writerows(forcing_rows)

    print('Generated /app/domain/params.json and /app/domain/forcing.csv')


if __name__ == '__main__':
    generate()
