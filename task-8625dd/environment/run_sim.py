"""Driver script for the 2D Navier-Stokes solver."""
import sys
import os
import numpy as np

try:
    import tomllib
except ImportError:
    import tomli as tomllib

sys.path.insert(0, '/app')
from ns2d import NS2DSolver

with open('/app/config.toml', 'rb') as f:
    config = tomllib.load(f)

sim = config['simulation']
solver = NS2DSolver(N=sim['N'], Re=sim['Re'], dt=sim['dt'],
                    dealias=sim['dealias'])

if sim['initial_condition'] == 'taylor_green':
    omega0 = solver.initialize_taylor_green()
else:
    raise ValueError(f"Unknown initial condition: {sim['initial_condition']}")

print(f"Running: N={sim['N']}, Re={sim['Re']}, dt={sim['dt']}, T={sim['T']}")
print(f"Initial energy:    {solver.compute_energy(omega0):.10e}")
print(f"Initial enstrophy: {solver.compute_enstrophy(omega0):.10e}")

result = solver.run(omega0, sim['T'])

print(f"Final energy:      {result['energies'][-1]:.10e}")
print(f"Final enstrophy:   {result['enstrophies'][-1]:.10e}")
print(f"Steps completed:   {len(result['times']) - 1}")

out_dir = config['output']['results_dir']
os.makedirs(out_dir, exist_ok=True)
np.savez(os.path.join(out_dir, 'simulation_output.npz'), **result)
print(f"Results saved to {out_dir}/simulation_output.npz")
