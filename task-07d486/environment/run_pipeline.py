#!/usr/bin/env python3

"""Ewald summation pipeline runner.

Loads crystal configurations, computes electrostatic properties,
and performs validation against reference values.
"""
import sys
sys.path.insert(0, '/app')

import numpy as np
from src.ewald_real import compute_real_space
from src.ewald_recip import compute_reciprocal
from src.ewald_self import compute_self_energy
from src.io_utils import load_system, load_parameters


def compute_madelung(total_energy, d, n_particles):
    """Extract Madelung constant from crystal energy.

    For a NaCl-type crystal: M = -2 * E * d / N
    """
    return 2.0 * total_energy * d / n_particles


def main():
    params = load_parameters('/app/data/params.ini')
    alpha = params['alpha']
    k_max = params['k_max']

    # Load and compute for perfect crystal
    crystal = load_system('/app/data/nacl_crystal.npz')
    E_real, F_real = compute_real_space(
        crystal['positions'], crystal['charges'], crystal['box_length'], alpha
    )
    E_recip, F_recip = compute_reciprocal(
        crystal['positions'], crystal['charges'], crystal['box_length'], alpha, k_max
    )
    E_self = compute_self_energy(crystal['charges'], alpha)

    E_total = E_real + E_recip + E_self
    F_total = F_real + F_recip

    madelung = compute_madelung(E_total, crystal['d'], crystal['n_particles'])
    max_force = float(np.max(np.linalg.norm(F_total, axis=1)))

    print(f"[COMPUTE] Real-space energy:     {E_real:.4f}")
    print(f"[COMPUTE] Reciprocal energy:       {E_recip:.4f}")
    print(f"[COMPUTE] Self-energy:           {E_self:.4f}")
    print(f"[COMPUTE] Total energy:          {E_total:.4f}")
    print(f"[COMPUTE] Madelung constant:      {madelung:.4f}")
    print(f"[COMPUTE] Max crystal force:        {max_force:.4f}")


if __name__ == '__main__':
    main()
