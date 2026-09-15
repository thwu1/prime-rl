#!/usr/bin/env python3
"""Analyze simulation data: compute velocity magnitude and temperature statistics."""
import numpy as np
import adios2
import json
import os

os.chdir("/app")

with adios2.FileReader("simulation.bp") as s:
    vars_info = s.available_variables()
    total_steps = int(vars_info["Ux"]["AvailableStepsCount"])

    results = {
        "steps_analyzed": [],
        "max_velocity_magnitude": [],
        "max_velocity_location": [],
        "avg_temperature": [],
        "total_steps_in_file": total_steps
    }

    for step in [0, 2, 4, 6]:
        Ux = s.read("Ux", step_selection=[step, 1])
        Uy = s.read("Uy", step_selection=[step, 1])
        Uz = s.read("Uz", step_selection=[step, 1])
        temp = s.read("temperature", step_selection=[step, 1])

        vel_mag = np.sqrt(Ux + Uy + Uz)

        max_vel = float(np.max(vel_mag))
        max_idx = np.unravel_index(np.argmax(vel_mag), vel_mag.shape)
        avg_temp = float(np.mean(temp))

        results["steps_analyzed"].append(step)
        results["max_velocity_magnitude"].append(round(max_vel, 6))
        results["max_velocity_location"].append([int(x) for x in max_idx])
        results["avg_temperature"].append(round(avg_temp, 6))

os.makedirs("/app/output", exist_ok=True)
with open("/app/output/analysis.json", "w") as f:
    json.dump(results, f, indent=2)

print("Analysis complete: /app/output/analysis.json")
