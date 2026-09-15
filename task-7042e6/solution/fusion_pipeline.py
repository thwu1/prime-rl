#!/usr/bin/env python3
"""
Multi-source ADIOS2 data fusion pipeline.

Reads three sensor BP5 datasets with different spatial resolutions and temporal
sampling rates, fuses them at the velocity sensor's resolution and timebase,
computes derived quantities, detects anomalies, and writes the output.

"""
import adios2
import json
import os
import shutil

import numpy as np

os.chdir("/app")

# Remove previous outputs
for p in ["fused.bp", "results"]:
    if os.path.exists(p):
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)


# ════════════════════════════════════════════════════════════════════
# Read source sensor data
# ════════════════════════════════════════════════════════════════════

def read_sensor(path):
    """Read all timesteps and metadata from a sensor BP5 file."""
    reader = adios2.FileReader(path)
    vars_info = reader.available_variables()
    attrs = reader.available_attributes()

    # Identify field variables (everything except 'time')
    field_vars = [v for v in vars_info if v != "time"]
    nsteps = max(int(vars_info[v]["AvailableStepsCount"]) for v in field_vars)

    # Read time values at each step
    times = []
    for step in range(nsteps):
        t = float(reader.read("time", step_selection=[step, 1]))
        times.append(t)

    # Read grid shape from first field variable
    first_var = field_vars[0]
    shape = [int(x) for x in vars_info[first_var]["Shape"].split(",") if x.strip()]

    # Read all field data for all steps
    data = {}
    for v in field_vars:
        data[v] = []
        for step in range(nsteps):
            arr = reader.read(v, step_selection=[step, 1])
            data[v].append(arr.astype(np.float64))

    reader.close()
    return {
        "times": times,
        "shape": shape,
        "data": data,
        "nsteps": nsteps,
        "field_vars": field_vars,
    }


print("Reading sensor datasets...")
vel_sensor = read_sensor("/app/data/sensor_velocity.bp")
temp_sensor = read_sensor("/app/data/sensor_temperature.bp")
press_sensor = read_sensor("/app/data/sensor_pressure.bp")

# Target grid = velocity sensor grid
Nx, Ny = vel_sensor["shape"]
fused_times = vel_sensor["times"]
num_fused_steps = vel_sensor["nsteps"]

print(f"Velocity sensor: {vel_sensor['shape']}, {vel_sensor['nsteps']} steps")
print(f"Temperature sensor: {temp_sensor['shape']}, {temp_sensor['nsteps']} steps")
print(f"Pressure sensor: {press_sensor['shape']}, {press_sensor['nsteps']} steps")
print(f"Target grid: {Nx}x{Ny}, {num_fused_steps} steps")


# ════════════════════════════════════════════════════════════════════
# Interpolation helpers
# ════════════════════════════════════════════════════════════════════

def bilinear_upsample(src, Tx, Ty):
    """Corner-aligned bilinear interpolation from src to (Tx, Ty)."""
    Sx, Sy = src.shape
    if Sx == Tx and Sy == Ty:
        return src.copy()

    it_arr = np.arange(Tx, dtype=np.float64)
    jt_arr = np.arange(Ty, dtype=np.float64)

    xs = it_arr * (Sx - 1) / (Tx - 1)
    ys = jt_arr * (Sy - 1) / (Ty - 1)

    x0 = np.floor(xs).astype(int)
    x1 = np.minimum(x0 + 1, Sx - 1)
    y0 = np.floor(ys).astype(int)
    y1 = np.minimum(y0 + 1, Sy - 1)

    fx = (xs - x0)[:, np.newaxis]
    fy = (ys - y0)[np.newaxis, :]

    return (
        (1 - fx) * (1 - fy) * src[np.ix_(x0, y0)]
        + fx * (1 - fy) * src[np.ix_(x1, y0)]
        + (1 - fx) * fy * src[np.ix_(x0, y1)]
        + fx * fy * src[np.ix_(x1, y1)]
    )


def temporal_interp(target_time, source_times, source_data_list):
    """Linear temporal interpolation with boundary clamping."""
    if target_time <= source_times[0]:
        return source_data_list[0].copy()
    if target_time >= source_times[-1]:
        return source_data_list[-1].copy()
    for idx in range(len(source_times) - 1):
        if source_times[idx] <= target_time <= source_times[idx + 1]:
            w = ((target_time - source_times[idx])
                 / (source_times[idx + 1] - source_times[idx]))
            return (1 - w) * source_data_list[idx] + w * source_data_list[idx + 1]
    return source_data_list[-1].copy()


# ════════════════════════════════════════════════════════════════════
# Fuse and write
# ════════════════════════════════════════════════════════════════════

ANOMALY_THRESHOLD = 400.0

adios_obj = adios2.Adios()
io_out = adios_obj.declare_io("FusedIO")

report = {
    "output_grid": [Nx, Ny],
    "num_fused_steps": num_fused_steps,
    "source_sensors": ["sensor_velocity", "sensor_temperature", "sensor_pressure"],
    "anomaly_threshold": ANOMALY_THRESHOLD,
    "anomalous_steps": [],
    "per_step_stats": [],
}

print("Writing fused.bp...")

with adios2.Stream(io_out, "fused.bp", "w") as s:
    for _ in s.steps(num_fused_steps):
        fused_step = s.current_step()
        t = fused_times[fused_step]

        # ── Velocity: direct passthrough ──
        Ux = vel_sensor["data"]["Ux"][fused_step]
        Uy = vel_sensor["data"]["Uy"][fused_step]

        # ── Temperature: temporal interp at source res, then spatial upsample ──
        temp_at_source_res = temporal_interp(
            t, temp_sensor["times"], temp_sensor["data"]["T"]
        )
        temperature = bilinear_upsample(temp_at_source_res, Nx, Ny)

        # ── Pressure: temporal interp at source res, then spatial upsample ──
        press_at_source_res = temporal_interp(
            t, press_sensor["times"], press_sensor["data"]["P"]
        )
        pressure = bilinear_upsample(press_at_source_res, Nx, Ny)

        # ── Derived variables ──
        speed = np.sqrt(Ux ** 2 + Uy ** 2)
        kinetic_energy = 0.5 * (Ux ** 2 + Uy ** 2)
        dUy_dx = np.gradient(Uy, axis=0)
        dUx_dy = np.gradient(Ux, axis=1)
        vorticity = dUy_dx - dUx_dy

        # ── Write to BP5 ──
        shape = [Nx, Ny]
        start = [0, 0]
        count = [Nx, Ny]

        s.write("velocity/Ux", Ux.astype(np.float64), shape, start, count)
        s.write("velocity/Uy", Uy.astype(np.float64), shape, start, count)
        s.write("temperature", temperature.astype(np.float64), shape, start, count)
        s.write("pressure", pressure.astype(np.float64), shape, start, count)
        s.write("derived/vorticity", vorticity.astype(np.float64), shape, start, count)
        s.write("derived/kinetic_energy", kinetic_energy.astype(np.float64), shape, start, count)
        s.write("derived/speed", speed.astype(np.float64), shape, start, count)
        s.write("physical_time", np.float64(t))

        # ── Attributes (first step only) ──
        if fused_step == 0:
            s.write_attribute("velocity/Ux/unit", "m/s")
            s.write_attribute("velocity/Uy/unit", "m/s")
            s.write_attribute("temperature/unit", "K")
            s.write_attribute("pressure/unit", "Pa")
            s.write_attribute("derived/vorticity/unit", "1/s")
            s.write_attribute("derived/kinetic_energy/unit", "m^2/s^2")
            s.write_attribute("derived/speed/unit", "m/s")
            s.write_attribute("Nx", np.int64(Nx))
            s.write_attribute("Ny", np.int64(Ny))
            s.write_attribute("dt", np.float64(fused_times[1] - fused_times[0]))

        # ── Anomaly detection ──
        max_temp = float(np.max(temperature))
        anomaly_detected = max_temp > ANOMALY_THRESHOLD
        if anomaly_detected:
            report["anomalous_steps"].append(fused_step)

        # ── Per-step statistics ──
        max_speed = float(np.max(speed))
        max_speed_idx = np.unravel_index(np.argmax(speed), speed.shape)

        stats = {
            "step": fused_step,
            "time": round(t, 6),
            "max_speed": round(max_speed, 6),
            "max_speed_location": [int(max_speed_idx[0]), int(max_speed_idx[1])],
            "mean_temperature": round(float(np.mean(temperature)), 6),
            "mean_pressure": round(float(np.mean(pressure)), 6),
            "max_abs_vorticity": round(float(np.max(np.abs(vorticity))), 6),
            "temperature_anomaly_detected": anomaly_detected,
        }
        report["per_step_stats"].append(stats)

        print(f"  Step {fused_step} (t={t:.1f}): max_speed={max_speed:.4f}, "
              f"anomaly={'YES' if anomaly_detected else 'no'}")

# ── Write report ──
os.makedirs("/app/results", exist_ok=True)
with open("/app/results/fusion_report.json", "w") as f:
    json.dump(report, f, indent=2)

print(f"\nFusion complete: {num_fused_steps} steps at {Nx}x{Ny}")
print(f"Anomalous steps: {report['anomalous_steps']}")
print("Output: /app/fused.bp, /app/results/fusion_report.json")
