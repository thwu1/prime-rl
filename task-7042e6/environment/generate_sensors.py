#!/usr/bin/env python3
"""Generate three sensor BP5 datasets for the multi-source fusion task.

Each sensor has different spatial resolution, temporal sampling, and variable naming.
The temperature sensor has a deliberate anomaly (spike) at one timestep.
"""
import numpy as np
import adios2
import os

os.makedirs("/app/data", exist_ok=True)

adios_obj = adios2.Adios()

# ════════════════════════════════════════════════════════════════════
# Sensor 1: Velocity (PIV) — primary timebase and grid
# Grid: 64x48, 8 steps, dt=0.1, times: [0.0, 0.1, ..., 0.7]
# ════════════════════════════════════════════════════════════════════
Nx_v, Ny_v = 64, 48
nsteps_v = 8
dt_v = 0.1

io_v = adios_obj.declare_io("VelocityIO")
with adios2.Stream(io_v, "/app/data/sensor_velocity.bp", "w") as s:
    for _ in s.steps(nsteps_v):
        step = s.current_step()
        t = step * dt_v
        i = np.arange(Nx_v, dtype=np.float64)
        j = np.arange(Ny_v, dtype=np.float64)
        ii, jj = np.meshgrid(i, j, indexing="ij")

        Ux = np.sin(2.0 * np.pi * ii / Nx_v) * np.cos(2.0 * np.pi * t)
        Uy = np.cos(2.0 * np.pi * jj / Ny_v) * np.sin(2.0 * np.pi * t)

        shape = [Nx_v, Ny_v]
        start = [0, 0]
        count = [Nx_v, Ny_v]

        s.write("Ux", Ux, shape, start, count)
        s.write("Uy", Uy, shape, start, count)
        s.write("time", np.float64(t))

        if step == 0:
            s.write_attribute("Ux/unit", "m/s")
            s.write_attribute("Uy/unit", "m/s")
            s.write_attribute("Nx", np.int64(Nx_v))
            s.write_attribute("Ny", np.int64(Ny_v))
            s.write_attribute("dt", np.float64(dt_v))
            s.write_attribute("sensor_name", "PIV_velocity")

print("Generated sensor_velocity.bp")

# ════════════════════════════════════════════════════════════════════
# Sensor 2: Temperature (Thermal Imaging) — lower res, different dt
# Grid: 32x24, 4 steps, dt=0.2, times: [0.0, 0.2, 0.4, 0.6]
# Has anomaly at step 2 (t=0.4): +500K spike at center [16,12]
# ════════════════════════════════════════════════════════════════════
Nx_t, Ny_t = 32, 24
nsteps_t = 4
dt_t = 0.2

io_t = adios_obj.declare_io("TemperatureIO")
with adios2.Stream(io_t, "/app/data/sensor_temperature.bp", "w") as s:
    for _ in s.steps(nsteps_t):
        step = s.current_step()
        t = step * dt_t
        i = np.arange(Nx_t, dtype=np.float64)
        j = np.arange(Ny_t, dtype=np.float64)
        ii, jj = np.meshgrid(i, j, indexing="ij")

        T = (300.0
             + 50.0 * np.sin(np.pi * ii / Nx_t)
             * np.sin(np.pi * jj / Ny_t)
             * np.exp(-0.5 * t))

        # Inject anomaly at step 2
        if step == 2:
            T[16, 12] += 500.0

        shape = [Nx_t, Ny_t]
        start = [0, 0]
        count = [Nx_t, Ny_t]

        s.write("T", T, shape, start, count)
        s.write("time", np.float64(t))

        if step == 0:
            s.write_attribute("T/unit", "K")
            s.write_attribute("Nx", np.int64(Nx_t))
            s.write_attribute("Ny", np.int64(Ny_t))
            s.write_attribute("dt", np.float64(dt_t))
            s.write_attribute("sensor_name", "thermal_camera")
            s.write_attribute("expected_range_min", np.float64(250.0))
            s.write_attribute("expected_range_max", np.float64(350.0))
            s.write_attribute("anomaly_threshold", np.float64(400.0))

print("Generated sensor_temperature.bp")

# ════════════════════════════════════════════════════════════════════
# Sensor 3: Pressure (Pressure Taps) — sparse grid, different dt
# Grid: 16x12, 6 steps, dt=0.125, times: [0.0, 0.125, ..., 0.625]
# ════════════════════════════════════════════════════════════════════
Nx_p, Ny_p = 16, 12
nsteps_p = 6
dt_p = 0.125

io_p = adios_obj.declare_io("PressureIO")
with adios2.Stream(io_p, "/app/data/sensor_pressure.bp", "w") as s:
    for _ in s.steps(nsteps_p):
        step = s.current_step()
        t = step * dt_p
        i = np.arange(Nx_p, dtype=np.float64)
        j = np.arange(Ny_p, dtype=np.float64)
        ii, jj = np.meshgrid(i, j, indexing="ij")

        P = 101325.0 + 2000.0 * np.cos(2.0 * np.pi * ii / Nx_p) * (1.0 - 0.2 * t)

        shape = [Nx_p, Ny_p]
        start = [0, 0]
        count = [Nx_p, Ny_p]

        s.write("P", P, shape, start, count)
        s.write("time", np.float64(t))

        if step == 0:
            s.write_attribute("P/unit", "Pa")
            s.write_attribute("Nx", np.int64(Nx_p))
            s.write_attribute("Ny", np.int64(Ny_p))
            s.write_attribute("dt", np.float64(dt_p))
            s.write_attribute("sensor_name", "pressure_taps")

print("Generated sensor_pressure.bp")
print("All sensor datasets generated in /app/data/")
