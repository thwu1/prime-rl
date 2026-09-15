#!/usr/bin/env python3
"""Post-process MODFLOW 6 Henry model results."""

import json
import os
import sys

import flopy
import numpy as np

with open("/app/parameters.json") as f:
    params = json.load(f)

sw_conc = params["seawater"]["concentration"]
ncol = params["discretization"]["ncol"]
nlay = params["discretization"]["nlay"]
lx = params["aquifer"]["length_x"]
delr = lx / ncol

x_centers = np.array([delr / 2 + i * delr for i in range(ncol)])

# Find concentration output file
ucn_files = [f for f in os.listdir("/app/model") if f.endswith(".ucn")]
if not ucn_files:
    print("ERROR: No .ucn file found in /app/model/")
    sys.exit(1)

ucn_path = os.path.join("/app/model", ucn_files[0])
cobj = flopy.utils.HeadFile(ucn_path, precision="double", text="CONCENTRATION")
conc = cobj.get_data()

bottom_conc = conc[nlay - 1, 0, :].tolist()
print(f"Bottom layer concentrations: {bottom_conc}")


def find_isochlor_position(conc_array, x_array, target_conc):
    """Find x-position of a target concentration by linear interpolation."""
    for i in range(len(conc_array) - 1):
        c1, c2 = conc_array[i], conc_array[i + 1]
        if (c1 <= target_conc <= c2) or (c2 <= target_conc <= c1):
            frac = (target_conc - c1) / (c2 - c1)
            return x_array[i] + frac * (x_array[i + 1] - x_array[i])
    return None


target_50 = 0.5 * sw_conc
toe_position = find_isochlor_position(
    np.array(bottom_conc), x_centers, target_50
)
if toe_position is None:
    print("ERROR: Could not locate 50% isochlor")
    sys.exit(1)
print(f"Toe position (50% isochlor): {toe_position:.4f} m")

target_10 = 0.10 * sw_conc
target_90 = 0.90 * sw_conc
pos_10 = find_isochlor_position(np.array(bottom_conc), x_centers, target_10)
pos_90 = find_isochlor_position(np.array(bottom_conc), x_centers, target_90)
if pos_10 is None or pos_90 is None:
    print("ERROR: Could not locate 10% or 90% isochlor")
    sys.exit(1)
mixing_zone_width = pos_90 - pos_10
print(f"Mixing zone width: {mixing_zone_width:.4f} m")

results = {
    "bottom_concentrations": bottom_conc,
    "toe_position": float(toe_position),
    "mixing_zone_width": float(mixing_zone_width),
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
