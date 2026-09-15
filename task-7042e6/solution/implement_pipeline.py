#!/usr/bin/env python3
"""
Implement the complete multi-resolution ADIOS2 data pipeline.

This script:
1. Fixes the broken adios2_config.xml
2. Creates writer.py
3. Creates analyzer.py
4. Creates run_pipeline.sh
5. Runs the pipeline to produce climate.bp and report.json

"""
import os
import shutil
import subprocess
import sys

os.chdir("/app")

# Remove previous outputs
for path in ["climate.bp", "report.json"]:
    if os.path.exists(path):
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

# ── Step 1: Fix adios2_config.xml ──
# Bugs: wrong IO name (MultiResOutput → MultiResWriter),
#        wrong engine (BP4 → BP5),
#        wrong param name (SubStreams → NumSubFiles),
#        missing StatsLevel and BufferChunkSize
config_xml = '<?xml version="1.0"?>\n<adios-config>\n    <io name="MultiResWriter">\n        <engine type="BP5">\n            <parameter key="NumSubFiles" value="1"/>\n            <parameter key="StatsLevel" value="1"/>\n            <parameter key="BufferChunkSize" value="67108864"/>\n        </engine>\n    </io>\n</adios-config>\n'
with open("adios2_config.xml", "w") as f:
    f.write(config_xml)

# ── Step 2: Create writer.py ──
writer_code = r'''#!/usr/bin/env python3
"""Multi-resolution BP5 data writer."""
import numpy as np
import adios2
import sys
import os

sys.path.insert(0, "/app")
from fields import compute_fields, VARIABLE_NAMES, FULL_SHAPE, NUM_STEPS, DT

Nx, Ny, Nz = FULL_SHAPE
RESOLUTIONS = {
    "full": {"factor": 1, "shape": [Nx, Ny, Nz]},
    "half": {"factor": 2, "shape": [Nx // 2, Ny // 2, Nz // 2]},
    "quarter": {"factor": 4, "shape": [Nx // 4, Ny // 4, Nz // 4]},
}


def block_mean_downsample(arr, factor):
    if factor == 1:
        return arr.copy()
    nx, ny, nz = arr.shape
    return arr.reshape(
        nx // factor, factor,
        ny // factor, factor,
        nz // factor, factor,
    ).mean(axis=(1, 3, 5))


def upsample_nearest(arr, factor):
    if factor == 1:
        return arr.copy()
    return np.repeat(
        np.repeat(np.repeat(arr, factor, axis=0), factor, axis=1),
        factor, axis=2,
    )


def compute_psnr(full_data, downsampled_data, factor):
    reconstructed = upsample_nearest(downsampled_data, factor)
    mse = float(np.mean((full_data - reconstructed) ** 2))
    data_range = float(np.max(full_data) - np.min(full_data))
    if mse == 0:
        return 999.0
    return 10.0 * np.log10(data_range ** 2 / mse)


def compute_max_abs_error(full_data, downsampled_data, factor):
    reconstructed = upsample_nearest(downsampled_data, factor)
    return float(np.max(np.abs(full_data - reconstructed)))


def main():
    os.chdir("/app")
    adios_obj = adios2.Adios("adios2_config.xml")
    io = adios_obj.declare_io("MultiResWriter")

    with adios2.Stream(io, "climate.bp", "w") as stream:
        for _ in stream.steps(NUM_STEPS):
            step = stream.current_step()
            t = step * DT

            # Compute full resolution fields
            full_fields = compute_fields(*FULL_SHAPE, step, DT)

            # Write each resolution level
            for level, info in RESOLUTIONS.items():
                factor = info["factor"]
                shape = info["shape"]
                start = [0, 0, 0]
                count = shape[:]

                for var_name in VARIABLE_NAMES:
                    data = block_mean_downsample(full_fields[var_name], factor)
                    var_path = f"{level}/{var_name}"
                    stream.write(var_path, data.astype(np.float64), shape, start, count)

                    # Write quality attributes at step 0 for downsampled levels
                    if step == 0 and factor > 1:
                        psnr = compute_psnr(full_fields[var_name], data, factor)
                        max_err = compute_max_abs_error(full_fields[var_name], data, factor)
                        stream.write_attribute(f"{level}/{var_name}/psnr_db", np.float64(psnr))
                        stream.write_attribute(f"{level}/{var_name}/max_abs_error", np.float64(max_err))

            # Write physical_time scalar
            stream.write("physical_time", np.float64(t))

            # Global attributes at step 0
            if step == 0:
                stream.write_attribute("Nx", np.int64(Nx))
                stream.write_attribute("Ny", np.int64(Ny))
                stream.write_attribute("Nz", np.int64(Nz))
                stream.write_attribute("dt", np.float64(DT))
                stream.write_attribute("num_resolution_levels", np.int64(3))
                for lv, inf in RESOLUTIONS.items():
                    stream.write_attribute(f"{lv}/downsample_factor", np.int64(inf["factor"]))

    print("Writer complete: climate.bp")


if __name__ == "__main__":
    main()
'''
with open("writer.py", "w") as f:
    f.write(writer_code)

# ── Step 3: Create analyzer.py ──
analyzer_code = r'''#!/usr/bin/env python3
"""Multi-resolution quality analyzer and report generator."""
import numpy as np
import adios2
import json
import sys
import os

sys.path.insert(0, "/app")
from fields import compute_fields, VARIABLE_NAMES, FULL_SHAPE, NUM_STEPS, DT

Nx, Ny, Nz = FULL_SHAPE
FACTORS = {"full": 1, "half": 2, "quarter": 4}
SHAPES = {
    "full": [Nx, Ny, Nz],
    "half": [Nx // 2, Ny // 2, Nz // 2],
    "quarter": [Nx // 4, Ny // 4, Nz // 4],
}
TOLERANCES = [0.1, 0.01, 0.001]


def block_mean_downsample(arr, factor):
    if factor == 1:
        return arr.copy()
    nx, ny, nz = arr.shape
    return arr.reshape(
        nx // factor, factor,
        ny // factor, factor,
        nz // factor, factor,
    ).mean(axis=(1, 3, 5))


def upsample_nearest(arr, factor):
    if factor == 1:
        return arr.copy()
    return np.repeat(
        np.repeat(np.repeat(arr, factor, axis=0), factor, axis=1),
        factor, axis=2,
    )


def compute_quality_all_steps(var_name, level):
    factor = FACTORS[level]
    mse_list = []
    max_err_list = []
    data_range_max = 0.0

    for step in range(NUM_STEPS):
        F = compute_fields(*FULL_SHAPE, step, DT)[var_name]
        D = block_mean_downsample(F, factor)
        R = upsample_nearest(D, factor)
        mse_list.append(float(np.mean((F - R) ** 2)))
        max_err_list.append(float(np.max(np.abs(F - R))))
        dr = float(np.max(F) - np.min(F))
        if dr > data_range_max:
            data_range_max = dr

    mse_total = float(np.mean(mse_list))
    max_abs_error = max(max_err_list)

    if mse_total == 0:
        psnr = 999.0
    else:
        psnr = 10.0 * np.log10(data_range_max ** 2 / mse_total)

    if data_range_max == 0:
        nrmse = 0.0
    else:
        nrmse = float(np.sqrt(mse_total)) / data_range_max

    return {
        "psnr_db": round(psnr, 2),
        "max_abs_error": round(max_abs_error, 8),
        "nrmse": round(nrmse, 8),
    }


def main():
    os.chdir("/app")

    # Verify the BP5 file exists
    assert os.path.isdir("climate.bp"), "climate.bp not found"

    # Compute quality metrics for each variable at each downsampled level
    quality = {}
    nrmses = {}  # for adaptive selection

    for level in ["half", "quarter"]:
        quality[level] = {}
        nrmses[level] = {}
        for var_name in VARIABLE_NAMES:
            q = compute_quality_all_steps(var_name, level)
            quality[level][var_name] = q
            nrmses[level][var_name] = q["nrmse"]

    # Adaptive resolution selection
    adaptive = {}
    for var_name in VARIABLE_NAMES:
        adaptive[var_name] = {}
        for tol in TOLERANCES:
            tol_str = str(tol)
            if nrmses["quarter"][var_name] < tol:
                adaptive[var_name][tol_str] = "quarter"
            elif nrmses["half"][var_name] < tol:
                adaptive[var_name][tol_str] = "half"
            else:
                adaptive[var_name][tol_str] = "full"

    report = {
        "num_steps": NUM_STEPS,
        "resolution_shapes": SHAPES,
        "quality": quality,
        "adaptive_selection": adaptive,
    }

    with open("report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Analyzer complete: report.json")


if __name__ == "__main__":
    main()
'''
with open("analyzer.py", "w") as f:
    f.write(analyzer_code)

# ── Step 4: Create run_pipeline.sh ──
run_script = """#!/bin/bash
set -e
cd /app
rm -rf climate.bp report.json
python3 writer.py
python3 analyzer.py
echo "Pipeline complete."
"""
with open("run_pipeline.sh", "w") as f:
    f.write(run_script)
os.chmod("run_pipeline.sh", 0o755)

# ── Step 5: Run the pipeline ──
print("=" * 60)
print("Running pipeline...")
print("=" * 60)

r1 = subprocess.run([sys.executable, "writer.py"], capture_output=True, text=True)
print(r1.stdout)
if r1.returncode != 0:
    print("WRITER ERROR:", r1.stderr)
    sys.exit(1)

r2 = subprocess.run([sys.executable, "analyzer.py"], capture_output=True, text=True)
print(r2.stdout)
if r2.returncode != 0:
    print("ANALYZER ERROR:", r2.stderr)
    sys.exit(1)

# Verify outputs
assert os.path.exists("climate.bp"), "climate.bp not created"
assert os.path.exists("report.json"), "report.json not created"

import json
with open("report.json") as f:
    report = json.load(f)
print("Pipeline complete. Report summary:")
print(json.dumps(report, indent=2))
