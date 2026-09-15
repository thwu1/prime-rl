"""
Run Langmuir plasma oscillation test.

A uniform plasma with a small sinusoidal density perturbation should
exhibit oscillations at the plasma frequency omega_p. The electric field
energy oscillates at 2*omega_p (since E^2 ~ cos^2(omega*t) has double
the frequency).

Output: /app/output/langmuir_results.json with keys:
  - omega_p_measured: measured plasma frequency
  - omega_p_expected: expected value (1.0)
  - relative_error: |measured - expected|
  - max_momentum_error: max |total momentum| over time
"""
import json
import os
import numpy as np
from numpy.fft import rfft, rfftfreq
from pic_framework import PICSimulation

# Simulation parameters
L = 2 * np.pi
N_grid = 64
N_particles = 10000
dt = 0.02
N_steps = 3000  # Total time = 60.0
perturbation_amp = 0.001
perturbation_mode = 1

sim = PICSimulation(L, N_grid, N_particles, dt,
                    perturbation_amp=perturbation_amp,
                    perturbation_mode=perturbation_mode)

results = sim.run(N_steps, initialize_func='langmuir')

time = results['time']
field_energy = results['field_energy']
dt_out = time[1] - time[0]

# FFT of field energy to find oscillation frequency
fe_centered = field_energy - np.mean(field_energy)
spectrum = np.abs(rfft(fe_centered))
freqs = rfftfreq(len(fe_centered), d=dt_out)

# Dominant frequency (skip DC component)
peak_idx = np.argmax(spectrum[1:]) + 1
dominant_freq = freqs[peak_idx]
omega_field_energy = 2 * np.pi * dominant_freq

# Field energy oscillates at 2*omega_p, so divide by 2
omega_p_measured = omega_field_energy / 2.0

os.makedirs('/app/output', exist_ok=True)
output = {
    'omega_p_measured': float(omega_p_measured),
    'omega_p_expected': 1.0,
    'relative_error': float(abs(omega_p_measured - 1.0)),
    'max_momentum_error': float(np.max(np.abs(results['momentum'])))
}

with open('/app/output/langmuir_results.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"Langmuir oscillation test:")
print(f"  omega_p measured = {omega_p_measured:.6f}")
print(f"  omega_p expected = 1.0")
print(f"  relative error   = {abs(omega_p_measured - 1.0):.6f}")
print(f"  max momentum err = {np.max(np.abs(results['momentum'])):.2e}")
