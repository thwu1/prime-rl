#!/usr/bin/env python3
"""
Deploy the reference implementation and verify it against the Euler
cantilever buckling analytical solution.
"""
import shutil
import sys
import importlib

# Deploy reference implementation
shutil.copy('/solution/reference.py', '/app/fem_buckling.py')

# Verify by computing Euler buckling for a simple cantilever
sys.path.insert(0, '/app')
if 'fem_buckling' in sys.modules:
    importlib.reload(sys.modules['fem_buckling'])

from fem_buckling import elastic_critical_load_analysis
import numpy as np

E = 2.1e5
L = 10.0
r = 0.15
P_ref = 1.0
num_nodes = 11
n_elems = 10

z = np.linspace(0.0, L, num_nodes)
coords = np.column_stack([np.zeros_like(z), np.zeros_like(z), z])

A = np.pi * r ** 2
I_z = np.pi * r ** 4 / 4.0
I_rho = np.pi * r ** 4 / 2.0

elements = [
    dict(
        node_i=i, node_j=i + 1,
        E=E, nu=0.3, A=A,
        I_y=I_z, I_z=I_z, J=I_rho, I_rho=I_rho,
        local_z=np.array([1.0, 0.0, 0.0]),
    )
    for i in range(n_elems)
]

bcs = {0: [1, 1, 1, 1, 1, 1]}
loads = {n: [0.0] * 6 for n in range(num_nodes)}
loads[num_nodes - 1][2] = -P_ref

lam, mode = elastic_critical_load_analysis(coords, elements, bcs, loads)
Pcr_exact = np.pi ** 2 * E * I_z / (4.0 * L ** 2)
rel_err = abs(lam * P_ref - Pcr_exact) / Pcr_exact

print(f"Computed lambda: {lam:.6e}")
print(f"Pcr (numeric):   {lam * P_ref:.6e}")
print(f"Pcr (analytic):  {Pcr_exact:.6e}")
print(f"Relative error:  {rel_err:.3e}")

assert rel_err < 1e-5, f"Verification FAILED: rel_err = {rel_err:.3e}"
print("VERIFIED: Reference implementation is correct.")
