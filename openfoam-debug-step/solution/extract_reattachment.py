"""Extract reattachment length from sampled velocity data near the lower wall.

The reattachment point is where the streamwise velocity (U_x) changes sign
from negative (recirculation) to positive (attached flow) on the lower wall
downstream of the backward-facing step.
"""

import json
import os
import glob


def find_latest_sample_file():
    """Locate the most recent sampled U data file."""
    sample_dir = '/app/pitzDaily/postProcessing/sample'
    patterns = [
        os.path.join(sample_dir, '*', 'nearLowerWall_U.raw'),
        os.path.join(sample_dir, '*', 'nearLowerWall_U_Ux_Uy_Uz.raw'),
        os.path.join(sample_dir, '*', 'nearLowerWall*U*'),
    ]
    for pattern in patterns:
        files = glob.glob(pattern)
        if files:
            files.sort(key=lambda f: float(os.path.basename(os.path.dirname(f))))
            return files[-1]
    raise FileNotFoundError(f"No sample data found in {sample_dir}")


def parse_raw_data(filepath):
    """Parse OpenFOAM raw set output (x Ux Uy Uz)."""
    x_coords = []
    u_x = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    x_coords.append(float(parts[0]))
                    u_x.append(float(parts[1]))
                except ValueError:
                    continue
    return x_coords, u_x


def find_reattachment_point(x_coords, u_x):
    """Find x-location where U_x changes from negative to positive."""
    for i in range(len(u_x) - 1):
        if u_x[i] < 0 and u_x[i + 1] >= 0:
            # Linear interpolation for precise location
            frac = -u_x[i] / (u_x[i + 1] - u_x[i])
            return x_coords[i] + frac * (x_coords[i + 1] - x_coords[i])

    # Fallback: search from the position of minimum U_x forward
    if u_x:
        min_idx = u_x.index(min(u_x))
        for i in range(min_idx, len(u_x) - 1):
            if u_x[i] < 0 and u_x[i + 1] >= 0:
                frac = -u_x[i] / (u_x[i + 1] - u_x[i])
                return x_coords[i] + frac * (x_coords[i + 1] - x_coords[i])

    return None


def main():
    data_file = find_latest_sample_file()
    x_coords, u_x = parse_raw_data(data_file)

    if not x_coords:
        raise RuntimeError("No valid data points found in sample output")

    reattachment_x = find_reattachment_point(x_coords, u_x)

    if reattachment_x is None:
        raise RuntimeError(
            "Could not find reattachment point - U_x never changes sign. "
            "Check that the simulation converged and the sampling location is correct."
        )

    step_height = 0.0254
    reattachment_normalized = reattachment_x / step_height

    result = {"reattachment_length_normalized": round(reattachment_normalized, 3)}

    with open('/app/results.json', 'w') as f:
        json.dump(result, f)

    print(f"Reattachment point: x = {reattachment_x:.5f} m")
    print(f"Normalized reattachment length: {reattachment_normalized:.2f} step heights")


if __name__ == '__main__':
    main()
