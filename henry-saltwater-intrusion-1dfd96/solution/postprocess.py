#!/usr/bin/env python3
"""Post-process MODFLOW 6 Henry model results."""

import json

import flopy
import numpy as np

# Load parameters
with open("/app/parameters.json") as f:
    params = json.load(f)

sw_conc = params["seawater"]["concentration"]
ncol = params["discretization"]["ncol"]
lx = params["aquifer"]["length_x"]
delr = lx / ncol

# Cell center x-coordinates
x_centers = np.array([delr / 2 + i * delr for i in range(ncol)])

# Read concentration output
gwtname = "gwt_henry"
ucn_path = f"/app/model/{gwtname}.ucn"
cobj = flopy.utils.HeadFile(ucn_path, precision="double", text="CONCENTRATION")
conc = cobj.get_data()  # last time step

# Extract bottom layer concentrations (last layer, row 0, all columns)
nlay = params["discretization"]["nlay"]
bottom_conc = conc[nlay - 1, 0, :].tolist()

print(f"Bottom layer concentrations: {bottom_conc}")


def find_isochlor_position(conc_array, x_array, target_conc):
    """Find x-position of a target concentration by linear interpolation."""
    for i in range(len(conc_array) - 1):
        c1, c2 = conc_array[i], conc_array[i + 1]
        if (c1 <= target_conc <= c2) or (c2 <= target_conc <= c1):
            # Linear interpolation
            frac = (target_conc - c1) / (c2 - c1)
            return x_array[i] + frac * (x_array[i + 1] - x_array[i])
    return None


# Compute toe position (50% isochlor)
target_50 = 0.5 * sw_conc
toe_position = find_isochlor_position(
    np.array(bottom_conc), x_centers, target_50
)
print(f"Toe position (50% isochlor): {toe_position:.4f} m")

# Compute mixing zone width (10% to 90% isochlors)
target_10 = 0.10 * sw_conc
target_90 = 0.90 * sw_conc
pos_10 = find_isochlor_position(np.array(bottom_conc), x_centers, target_10)
pos_90 = find_isochlor_position(np.array(bottom_conc), x_centers, target_90)
mixing_zone_width = pos_90 - pos_10
print(f"10% isochlor position: {pos_10:.4f} m")
print(f"90% isochlor position: {pos_90:.4f} m")
print(f"Mixing zone width: {mixing_zone_width:.4f} m")

# Write results
results = {
    "bottom_concentrations": bottom_conc,
    "toe_position": float(toe_position),
    "mixing_zone_width": float(mixing_zone_width),
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
