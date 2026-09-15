#!/usr/bin/env python3
"""Generate reference measurement data in HDF5 format.
The true system has hidden thermal dynamics not present in the
incomplete model. Only pot temperature is exposed as measurements."""
import numpy as np
import h5py
from scipy.integrate import solve_ivp

# True system parameters (hidden from agent)
C1 = 1.0       # Hidden plate heat capacity
C2 = 15.0      # Pot heat capacity
G_cond = 1.0   # Thermal conductance plate-to-pot (HIDDEN)
G_air = 0.1    # Thermal conductance pot-to-air
T_env = 293.15 # Environment temperature
T0 = 273.15    # Initial temperature

def input_f(t):
    return (1 + np.sin(0.005 * t**2)) / 2

def full_system(t, y):
    T1, T2 = y
    dT1 = (input_f(t) - G_cond * (T1 - T2)) / C1
    dT2 = (G_cond * (T1 - T2) - G_air * (T2 - T_env)) / C2
    return [dT1, dT2]

# Generate training data
t_train = np.linspace(0, 100, 500)
sol_train = solve_ivp(full_system, [0, 100], [T0, T0], t_eval=t_train,
                      method='RK45', rtol=1e-12, atol=1e-12)

# Generate extrapolation time grid
t_extrap = np.linspace(100, 200, 500)

# Write HDF5
with h5py.File('/app/data/measurements.h5', 'w') as f:
    # Training measurements
    train_grp = f.create_group('training')
    train_grp.create_dataset('time', data=sol_train.t)
    train_grp.create_dataset('temperature', data=sol_train.y[1])
    train_grp.attrs['units_time'] = 'seconds'
    train_grp.attrs['units_temperature'] = 'kelvin'
    train_grp.attrs['description'] = 'Pot temperature measurements from thermal system'
    train_grp.attrs['num_points'] = len(sol_train.t)

    # Extrapolation time grid
    extrap_grp = f.create_group('extrapolation')
    extrap_grp.create_dataset('time', data=t_extrap)
    extrap_grp.attrs['description'] = 'Time grid for model extrapolation evaluation'

    # System metadata
    meta_grp = f.create_group('metadata')
    meta_grp.attrs['system_type'] = 'thermal'
    meta_grp.attrs['measurement_location'] = 'pot'
    meta_grp.attrs['num_observed_states'] = 1
    meta_grp.attrs['initial_temperature_K'] = T0

print(f"Generated HDF5 reference data: {len(sol_train.t)} training points")
print(f"T_pot range: [{sol_train.y[1].min():.4f}, {sol_train.y[1].max():.4f}] K")
