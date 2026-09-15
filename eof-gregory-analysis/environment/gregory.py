"""
Gregory regression for equilibrium climate sensitivity estimation.
Reads time-subsetted variables from an NCO-extracted NetCDF file.
"""
import numpy as np
from netCDF4 import Dataset
import json
import sys


def main():
    gregory_file = sys.argv[1]

    with Dataset(gregory_file) as nc:
        toa = np.array(nc.variables['toa_imbalance'][:])
        gmst = np.array(nc.variables['gmst_anomaly'][:])

    # Fit N = slope * T + intercept
    slope, intercept = np.polyfit(gmst, toa, 1)

    # Compute ECS: equilibrium when N = 0
    ecs = slope / intercept

    result = {
        "ecs_estimate": round(float(ecs), 4),
        "feedback_parameter": round(float(slope), 4)
    }

    with open('/tmp/pipeline_work/gregory_results.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f"  ECS = {ecs:.4f} K, feedback = {slope:.4f} W/m^2/K")


if __name__ == '__main__':
    main()
