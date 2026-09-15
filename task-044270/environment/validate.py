"""Quick validation: Euler buckling of a cantilever column."""
import numpy as np
from frame3d import elastic_critical_load_analysis

E, nu = 1000.0, 0.3
L, r = 10.0, 0.5
num_nodes = 11
n_elems = num_nodes - 1
P_ref = 1.0

z = np.linspace(0.0, L, num_nodes)
node_coords = np.c_[np.zeros_like(z), np.zeros_like(z), z]

A = np.pi * r ** 2
I = np.pi * r ** 4 / 4.0
J = np.pi * r ** 4 / 2.0

elements = [
    dict(
        node_i=i, node_j=i + 1, E=E, nu=nu, A=A,
        I_y=I, I_z=I, J=J, I_rho=2 * I,
        local_z=np.array([1.0, 0.0, 0.0]),
    )
    for i in range(n_elems)
]

boundary_conditions = {0: [True, True, True, True, True, True]}

nodal_loads = {n: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for n in range(num_nodes)}
nodal_loads[num_nodes - 1][2] = -P_ref

try:
    lam, mode = elastic_critical_load_analysis(
        node_coords=node_coords,
        elements=elements,
        boundary_conditions=boundary_conditions,
        nodal_loads=nodal_loads,
    )
    Pcr_computed = lam * P_ref
    Pcr_analytical = np.pi ** 2 * E * I / (4.0 * L ** 2)
    rel_err = abs(Pcr_computed - Pcr_analytical) / Pcr_analytical
    print(f"Computed critical load:  {Pcr_computed:.6e}")
    print(f"Analytical Euler value:  {Pcr_analytical:.6e}")
    print(f"Relative error:          {rel_err:.3e}")
    if rel_err < 1e-4:
        print("PASS")
    else:
        print("FAIL -- relative error exceeds tolerance")
except Exception as e:
    print(f"FAIL -- exception: {e}")
