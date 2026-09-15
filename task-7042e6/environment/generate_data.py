#!/usr/bin/env python3
"""Generate 3D fluid simulation data using ADIOS2 BP5 engine."""
import numpy as np
import adios2
import os

Nx, Ny, Nz = 64, 48, 32
num_steps = 8
dt = 0.1

os.chdir("/app")

adios_obj = adios2.Adios("config.xml")
io = adios_obj.declare_io("SimOutput")

with adios2.Stream(io, "simulation.bp", "w") as s:
    for _ in s.steps(num_steps):
        step = s.current_step()
        t = step * dt

        i = np.arange(Nx, dtype=np.float64)
        j = np.arange(Ny, dtype=np.float64)
        k = np.arange(Nz, dtype=np.float64)
        ii, jj, kk = np.meshgrid(i, j, k, indexing='ij')

        Ux = (np.sin(2 * np.pi * ii / Nx) * np.cos(2 * np.pi * t)).astype(np.float64)
        Uy = (np.cos(2 * np.pi * jj / Ny) * np.sin(2 * np.pi * t)).astype(np.float64)
        Uz = (0.5 * np.sin(2 * np.pi * kk / Nz) * np.cos(np.pi * t)).astype(np.float64)
        temperature = (300.0 + 100.0 * np.sin(np.pi * ii / Nx) *
                       np.sin(np.pi * jj / Ny) * np.exp(-t // 2)).astype(np.float64)
        pressure = (101325.0 + 5000.0 * np.cos(2 * np.pi * kk / Nz) *
                    (1.0 - 0.1 * t)).astype(np.float64)

        shape = [Nz, Ny, Nx]
        start = [0, 0, 0]
        count = [Nz, Ny, Nx]

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
