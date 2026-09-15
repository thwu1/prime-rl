"""
Run two-stream instability test.

Two counter-streaming electron beams should exhibit exponential growth
of the electric field energy during the linear phase. The growth rate
is compared against the analytic cold two-stream dispersion relation.

Output: /app/output/two_stream_results.json with keys:
  - growth_rate_measured: measured growth rate gamma
  - growth_rate_analytic: analytic prediction from dispersion relation
  - relative_error: |measured - analytic| / analytic
  - initial_field_energy: field energy at t ~ 0
  - final_field_energy: field energy at final time
  - max_momentum_error: max |total momentum| over time

Also writes: /app/output/phase_space.dat (particle x, v columns)
"""
import json
import os
import numpy as np
from pic_framework import PICSimulation

# Simulation parameters
L = 4 * np.pi
N_grid = 128
N_particles = 40000
dt = 0.05
N_steps = 800  # Total time = 40
v0 = 1.0
perturbation_amp = 0.01
perturbation_mode = 1

sim = PICSimulation(L, N_grid, N_particles, dt, v0=v0,
                    perturbation_amp=perturbation_amp,
                    perturbation_mode=perturbation_mode)

results = sim.run(N_steps, initialize_func='two_stream')

time = results['time']
field_energy = results['field_energy']

# --- Save phase-space data (particle positions and velocities at final time) ---
os.makedirs('/app/output', exist_ok=True)
phase_data = np.column_stack([sim.x, sim.v])
np.savetxt('/app/output/phase_space.dat', phase_data, header='x v', comments='# ')

# --- Extract growth rate from exponential phase ---
# The field energy contains both the growing mode and stable oscillatory modes.
# Smooth with a running average over one oscillation period (~5 time units for
# this k and v0) to isolate the exponential growth envelope.
log_energy = np.log(field_energy + 1e-50)
initial_energy = field_energy[1]

osc_period_steps = max(int(5.0 / dt), 5)
if osc_period_steps % 2 == 0:
    osc_period_steps += 1
kernel = np.ones(osc_period_steps) / osc_period_steps
log_smooth = np.convolve(log_energy, kernel, mode='valid')
t_smooth = time[osc_period_steps // 2 : osc_period_steps // 2 + len(log_smooth)]

# Find growth region in smoothed data
log_init_s = log_smooth[0]
log_max_s = np.max(log_smooth)
log_range_s = log_max_s - log_init_s

log_lo_s = log_init_s + 0.20 * log_range_s
log_hi_s = log_init_s + 0.70 * log_range_s
mask = (log_smooth >= log_lo_s) & (log_smooth <= log_hi_s)

# Ensure contiguous fitting window (avoid post-saturation re-entries)
if np.sum(mask) >= 2:
    indices = np.where(mask)[0]
    breaks = np.where(np.diff(indices) > 1)[0]
    if len(breaks) > 0:
        mask = np.zeros_like(mask, dtype=bool)
        mask[indices[:breaks[0] + 1]] = True

if np.sum(mask) < 10:
    mask = (t_smooth > 5) & (t_smooth < 20)

t_fit = t_smooth[mask]
log_e_fit = log_smooth[mask]

# Linear fit: log(E_field) = 2*gamma*t + const
coeffs = np.polyfit(t_fit, log_e_fit, 1)
growth_rate_measured = coeffs[0] / 2.0

# --- Analytic growth rate from cold two-stream dispersion relation ---
# Dispersion: 1 = (wp^2/2) * [1/(w-kv0)^2 + 1/(w+kv0)^2]
# For purely growing mode w = i*gamma:
#   (k^2*v0^2 + gamma^2)^2 = wp^2 * (k^2*v0^2 - gamma^2)
# Solving: gamma^2 = [-(2a + wp^2) + wp*sqrt(8*a*wp^2 + wp^4)] / 2
# where a = k^2 * v0^2
k1 = 2 * np.pi * perturbation_mode / L
omega_p = 1.0
a = k1**2 * v0**2
wp2 = omega_p**2
discriminant = 8 * a * wp2 + wp2**2
u = (-(2 * a + wp2) + omega_p * np.sqrt(discriminant)) / 2.0
growth_rate_analytic = np.sqrt(max(u, 0.0))

relative_error = abs(growth_rate_measured - growth_rate_analytic) / growth_rate_analytic

output = {
    'growth_rate_measured': float(growth_rate_measured),
    'growth_rate_analytic': float(growth_rate_analytic),
    'relative_error': float(relative_error),
    'initial_field_energy': float(initial_energy),
    'final_field_energy': float(field_energy[-1]),
    'max_momentum_error': float(np.max(np.abs(results['momentum'])))
}

with open('/app/output/two_stream_results.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"Two-stream instability test:")
print(f"  growth rate measured = {growth_rate_measured:.6f}")
print(f"  growth rate analytic = {growth_rate_analytic:.6f}")
print(f"  relative error       = {relative_error:.4f}")
print(f"  initial field energy = {initial_energy:.2e}")
print(f"  final field energy   = {field_energy[-1]:.2e}")
print(f"  max momentum error   = {np.max(np.abs(results['momentum'])):.2e}")
