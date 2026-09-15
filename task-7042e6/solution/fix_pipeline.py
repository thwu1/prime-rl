#!/usr/bin/env python3
"""
Fix all bugs in the ADIOS2 data pipeline and run it end-to-end.

"""
import os
import shutil
import subprocess
import sys

os.chdir("/app")

# Remove previous outputs
for p in ["simulation.bp", "results", "output"]:
    if os.path.exists(p):
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)

# ── Fix 1: adios2_config.xml ──
# Bug A: engine type BP4 → BP5
# Bug B: SubStreams (BP4-only param) → NumSubFiles (BP5 param)
# Add recommended BP5 parameters
config_xml = """\
<?xml version="1.0"?>
<adios-config>
    <io name="SimOutput">
        <engine type="BP5">
            <parameter key="NumSubFiles" value="1"/>
            <parameter key="StatsLevel" value="1"/>
            <parameter key="BufferChunkSize" value="67108864"/>
        </engine>
    </io>
</adios-config>
"""
with open("adios2_config.xml", "w") as f:
    f.write(config_xml)

# ── Fix 2: generate_data.py ──
# Bug A: config filename "config.xml" → "adios2_config.xml"
# Bug B: shape/count arrays reversed [Nz,Ny,Nx] → [Nx,Ny,Nz]
# Bug C: temperature uses -t//2 (floor division) → -0.5*t (float multiply)
generate_py = '''\
#!/usr/bin/env python3
"""Generate 3D fluid simulation data using ADIOS2 BP5 engine."""
import numpy as np
import adios2
import os

Nx, Ny, Nz = 64, 48, 32
num_steps = 8
dt = 0.1

os.chdir("/app")

adios_obj = adios2.Adios("adios2_config.xml")
io = adios_obj.declare_io("SimOutput")

with adios2.Stream(io, "simulation.bp", "w") as s:
    for _ in s.steps(num_steps):
        step = s.current_step()
        t = step * dt

        i = np.arange(Nx, dtype=np.float64)
        j = np.arange(Ny, dtype=np.float64)
        k = np.arange(Nz, dtype=np.float64)
        ii, jj, kk = np.meshgrid(i, j, k, indexing=\'ij\')

        Ux = (np.sin(2 * np.pi * ii / Nx) * np.cos(2 * np.pi * t)).astype(np.float64)
        Uy = (np.cos(2 * np.pi * jj / Ny) * np.sin(2 * np.pi * t)).astype(np.float64)
        Uz = (0.5 * np.sin(2 * np.pi * kk / Nz) * np.cos(np.pi * t)).astype(np.float64)
        temperature = (300.0 + 100.0 * np.sin(np.pi * ii / Nx) *
                       np.sin(np.pi * jj / Ny) * np.exp(-0.5 * t)).astype(np.float64)
        pressure = (101325.0 + 5000.0 * np.cos(2 * np.pi * kk / Nz) *
                    (1.0 - 0.1 * t)).astype(np.float64)

        shape = [Nx, Ny, Nz]
        start = [0, 0, 0]
        count = [Nx, Ny, Nz]

        s.write("velocity/Ux", Ux, shape, start, count)
        s.write("velocity/Uy", Uy, shape, start, count)
        s.write("velocity/Uz", Uz, shape, start, count)
        s.write("temperature", temperature, shape, start, count)
        s.write("pressure", pressure, shape, start, count)
        s.write("physical_time", np.float64(t))

        if step == 0:
            s.write_attribute("velocity/Ux/unit", "m/s")
            s.write_attribute("velocity/Uy/unit", "m/s")
            s.write_attribute("velocity/Uz/unit", "m/s")
            s.write_attribute("temperature/unit", "K")
            s.write_attribute("pressure/unit", "Pa")
            s.write_attribute("Nx", np.int64(Nx))
            s.write_attribute("Ny", np.int64(Ny))
            s.write_attribute("Nz", np.int64(Nz))
            s.write_attribute("dt", np.float64(dt))

print("Data generation complete: simulation.bp")
'''
with open("generate_data.py", "w") as f:
    f.write(generate_py)

# ── Fix 3: analyze_data.py ──
# Bug A: variable names "Ux" → "velocity/Ux" etc. (hierarchical ADIOS2 naming)
# Bug B: velocity magnitude sqrt(Ux+Uy+Uz) → sqrt(Ux**2+Uy**2+Uz**2)
# Bug C: output path /app/output/ → /app/results/
analyze_py = '''\
#!/usr/bin/env python3
"""Analyze simulation data: compute velocity magnitude and temperature statistics."""
import numpy as np
import adios2
import json
import os

os.chdir("/app")

with adios2.FileReader("simulation.bp") as s:
    vars_info = s.available_variables()
    total_steps = int(vars_info["velocity/Ux"]["AvailableStepsCount"])

    results = {
        "steps_analyzed": [],
        "max_velocity_magnitude": [],
        "max_velocity_location": [],
        "avg_temperature": [],
        "total_steps_in_file": total_steps
    }

    for step in [0, 2, 4, 6]:
        Ux = s.read("velocity/Ux", step_selection=[step, 1])
        Uy = s.read("velocity/Uy", step_selection=[step, 1])
        Uz = s.read("velocity/Uz", step_selection=[step, 1])
        temp = s.read("temperature", step_selection=[step, 1])

        vel_mag = np.sqrt(Ux**2 + Uy**2 + Uz**2)

        max_vel = float(np.max(vel_mag))
        max_idx = np.unravel_index(np.argmax(vel_mag), vel_mag.shape)
        avg_temp = float(np.mean(temp))

        results["steps_analyzed"].append(step)
        results["max_velocity_magnitude"].append(round(max_vel, 6))
        results["max_velocity_location"].append([int(x) for x in max_idx])
        results["avg_temperature"].append(round(avg_temp, 6))

os.makedirs("/app/results", exist_ok=True)
with open("/app/results/analysis.json", "w") as f:
    json.dump(results, f, indent=2)

print("Analysis complete: /app/results/analysis.json")
'''
with open("analyze_data.py", "w") as f:
    f.write(analyze_py)

# ── Run the fixed pipeline ──
print("=" * 60)
print("Running fixed pipeline...")
print("=" * 60)

r1 = subprocess.run([sys.executable, "generate_data.py"], capture_output=True, text=True)
print(r1.stdout)
if r1.returncode != 0:
    print("GENERATE ERROR:", r1.stderr)
    sys.exit(1)

r2 = subprocess.run([sys.executable, "analyze_data.py"], capture_output=True, text=True)
print(r2.stdout)
if r2.returncode != 0:
    print("ANALYZE ERROR:", r2.stderr)
    sys.exit(1)

# Verify outputs exist
assert os.path.exists("/app/results/analysis.json"), "analysis.json not created"

import json
with open("/app/results/analysis.json") as f:
    report = json.load(f)
print("Pipeline fixed and run successfully.")
print(json.dumps(report, indent=2))
