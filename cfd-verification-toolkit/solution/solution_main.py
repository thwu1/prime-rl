#!/usr/bin/env python3
"""
CFD Solution Verification Pipeline — Reference Solution
"""

import math
import json
import os
import subprocess
import numpy as np
import meshio


# ===================================================================
# 1. Compressible flow relations
# ===================================================================

def normal_shock(M1, gamma=1.4):
    """Normal shock jump conditions."""
    g = gamma
    M2_sq = (1 + (g - 1) / 2 * M1 ** 2) / (g * M1 ** 2 - (g - 1) / 2)
    M2 = math.sqrt(M2_sq)
    p2_p1 = 1 + 2 * g / (g + 1) * (M1 ** 2 - 1)
    rho2_rho1 = (g + 1) * M1 ** 2 / (2 + (g - 1) * M1 ** 2)
    T2_T1 = p2_p1 / rho2_rho1

    ratio = ((1 + (g - 1) / 2 * M2_sq) /
             (1 + (g - 1) / 2 * M1 ** 2)) ** (g / (g - 1))
    p02_p01 = p2_p1 * ratio

    return {
        'M2': M2,
        'p2_p1': p2_p1,
        'rho2_rho1': rho2_rho1,
        'T2_T1': T2_T1,
        'p02_p01': p02_p01,
    }


def isentropic_relations(M, gamma=1.4):
    """Isentropic flow ratios as function of Mach number."""
    g = gamma
    factor = 1 + (g - 1) / 2 * M ** 2
    T_T0 = 1.0 / factor
    p_p0 = T_T0 ** (g / (g - 1))
    rho_rho0 = T_T0 ** (1 / (g - 1))
    A_Astar = (1 / M) * ((2 / (g + 1)) * factor) ** ((g + 1) / (2 * (g - 1)))

    return {
        'p_p0': p_p0,
        'T_T0': T_T0,
        'rho_rho0': rho_rho0,
        'A_Astar': A_Astar,
    }


# ===================================================================
# 2. CI2 vortex-shock initial condition (ported from legacy Py2 script)
# ===================================================================

def ci2_evaluate(x, y):
    """Evaluate CI2 vortex-shock initial condition at (x, y)."""
    g = 1.4
    R = 1.0
    M_s = 1.5
    M_v = 0.9

    rho_u = 1.0
    u_u = M_s * math.sqrt(g)
    v_u = 1.0e-20
    p_u = 1.0
    t_u = p_u / (rho_u * R)

    rho_d = rho_u * (g + 1) * M_s ** 2 / (2 + (g - 1) * M_s ** 2)
    u_d = u_u * (2 + (g - 1) * M_s ** 2) / ((g + 1) * M_s ** 2)
    v_d = v_u
    p_d = p_u * (1 + 2 * g / (g + 1) * (M_s ** 2 - 1))

    if x <= 0.5:
        pressure = p_u
        temperature = t_u
        vx, vy = u_u, v_u
    else:
        pressure = p_d
        temperature = p_d / (rho_d * R)
        vx, vy = u_d, v_d

    x_c, y_c = 0.25, 0.5
    a, b = 0.075, 0.175
    v_m = M_v * math.sqrt(g)

    dx = x - x_c
    dy = y - y_c
    r = math.sqrt(dx ** 2 + dy ** 2)

    if 0 < r <= b:
        sin_t = dy / r
        cos_t = dx / r

        if r <= a:
            mag = v_m * r / a
            vx -= mag * sin_t
            vy += mag * cos_t

            radial_term = (-2.0 * b ** 2 * math.log(b) - 0.5 * a ** 2 +
                           2.0 * b ** 2 * math.log(a) +
                           0.5 * b ** 4 / a ** 2)
            t_a = t_u - ((g - 1) *
                         (v_m * a / (a ** 2 - b ** 2)) ** 2 *
                         radial_term / (R * g))
            radial_inner = 0.5 * (1.0 - r ** 2 / a ** 2)
            temperature = t_a - (g - 1) * v_m ** 2 * radial_inner / (R * g)
        else:
            mag = v_m * a * (r - b ** 2 / r) / (a ** 2 - b ** 2)
            vx -= mag * sin_t
            vy += mag * cos_t

            radial_term = (-2.0 * b ** 2 * math.log(b) - 0.5 * r ** 2 +
                           2.0 * b ** 2 * math.log(r) +
                           0.5 * b ** 4 / r ** 2)
            temperature = t_u - ((g - 1) *
                                 (v_m * a / (a ** 2 - b ** 2)) ** 2 *
                                 radial_term / (R * g))

        pressure = p_u * (temperature / t_u) ** (g / (g - 1))

    return {
        'pressure': pressure,
        'temperature': temperature,
        'velocity_x': vx,
        'velocity_y': vy,
    }


# ===================================================================
# 3. Grid convergence analysis
# ===================================================================

def load_convergence_data(path):
    """Load (h, f) data from CSV file."""
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('h'):
                continue
            parts = line.split(',')
            data.append((float(parts[0]), float(parts[1])))
    return sorted(data, key=lambda x: -x[0])


def analyze_convergence(data):
    """Compute observed order, extrapolated value, and uncertainty."""
    n = len(data)

    observed_orders = []
    for i in range(n - 2):
        f1, f2, f3 = data[i][1], data[i + 1][1], data[i + 2][1]
        h1, h2 = data[i][0], data[i + 1][0]
        r = h1 / h2

        delta_coarse = f1 - f2
        delta_fine = f2 - f3

        if abs(delta_fine) < 1e-15:
            p = float('inf')
        else:
            p = math.log(abs(delta_coarse / delta_fine)) / math.log(r)
        observed_orders.append(p)

    # Extrapolation from two finest grids
    p_obs = observed_orders[-1]
    f_fine = data[-1][1]
    f_coarse = data[-2][1]
    h_fine = data[-1][0]
    h_coarse = data[-2][0]
    r = h_coarse / h_fine

    extrapolated = f_fine + (f_fine - f_coarse) / (r ** p_obs - 1)

    # Uncertainty with Fs=1.25
    epsilon = (f_coarse - f_fine) / f_fine
    uncertainty = 1.25 * abs(epsilon) / (r ** p_obs - 1)

    return {
        'observed_orders': observed_orders,
        'extrapolated_value': extrapolated,
        'uncertainty_fine': uncertainty,
    }


# ===================================================================
# 4. MMS source terms for 2D steady compressible Euler equations
# ===================================================================

def mms_manufactured_solution(x, y):
    """Evaluate manufactured solution and its analytical derivatives."""
    pi = math.pi
    s2x = math.sin(2 * pi * x)
    c2x = math.cos(2 * pi * x)
    s2y = math.sin(2 * pi * y)
    c2y = math.cos(2 * pi * y)

    rho = 1.0 + 0.1 * s2x * c2y
    u = 0.5 + 0.05 * s2x
    v = 0.3 + 0.05 * c2y
    p = 1.0 + 0.2 * s2x * c2y

    drho_dx = 0.1 * 2 * pi * c2x * c2y
    drho_dy = -0.1 * 2 * pi * s2x * s2y
    du_dx = 0.05 * 2 * pi * c2x
    du_dy = 0.0
    dv_dx = 0.0
    dv_dy = -0.05 * 2 * pi * s2y
    dp_dx = 0.2 * 2 * pi * c2x * c2y
    dp_dy = -0.2 * 2 * pi * s2x * s2y

    return (rho, u, v, p,
            drho_dx, drho_dy, du_dx, du_dy, dv_dx, dv_dy, dp_dx, dp_dy)


def mms_source_terms(x, y, gamma=1.4):
    """Compute MMS source terms for 2D steady Euler at (x, y)."""
    g = gamma
    (rho, u, v, p,
     drho_dx, drho_dy, du_dx, du_dy, dv_dx, dv_dy, dp_dx, dp_dy
     ) = mms_manufactured_solution(x, y)

    E = p / (g - 1) + 0.5 * rho * (u ** 2 + v ** 2)
    dE_dx = (dp_dx / (g - 1) + 0.5 * (u ** 2 + v ** 2) * drho_dx +
             rho * u * du_dx + rho * v * dv_dx)
    dE_dy = (dp_dy / (g - 1) + 0.5 * (u ** 2 + v ** 2) * drho_dy +
             rho * u * du_dy + rho * v * dv_dy)

    S_mass = ((rho * du_dx + u * drho_dx) +
              (rho * dv_dy + v * drho_dy))

    S_xmom = ((2 * rho * u * du_dx + u ** 2 * drho_dx + dp_dx) +
              (rho * u * dv_dy + rho * v * du_dy + u * v * drho_dy))

    S_ymom = ((rho * v * du_dx + rho * u * dv_dx + u * v * drho_dx) +
              (2 * rho * v * dv_dy + v ** 2 * drho_dy + dp_dy))

    S_energy = (((dE_dx + dp_dx) * u + (E + p) * du_dx) +
                ((dE_dy + dp_dy) * v + (E + p) * dv_dy))

    return S_mass, S_xmom, S_ymom, S_energy


def mms_verify_residual(gamma=1.4, nx=50, ny=50):
    """Verify MMS source terms by recomputing flux divergence independently."""
    max_res = 0.0

    for i in range(nx):
        for j in range(ny):
            x = (i + 0.5) / nx
            y = (j + 0.5) / ny

            Sm, Sx, Sy, Se = mms_source_terms(x, y, gamma)

            g = gamma
            (rho, u, v, p,
             drho_dx, drho_dy, du_dx, du_dy,
             dv_dx, dv_dy, dp_dx, dp_dy
             ) = mms_manufactured_solution(x, y)

            E = p / (g - 1) + 0.5 * rho * (u ** 2 + v ** 2)
            dE_dx = (dp_dx / (g - 1) +
                     0.5 * (u ** 2 + v ** 2) * drho_dx +
                     rho * u * du_dx + rho * v * dv_dx)
            dE_dy = (dp_dy / (g - 1) +
                     0.5 * (u ** 2 + v ** 2) * drho_dy +
                     rho * u * du_dy + rho * v * dv_dy)

            dF0 = rho * du_dx + u * drho_dx
            dF1 = 2 * rho * u * du_dx + u ** 2 * drho_dx + dp_dx
            dF2 = rho * v * du_dx + rho * u * dv_dx + u * v * drho_dx
            dF3 = (dE_dx + dp_dx) * u + (E + p) * du_dx

            dG0 = rho * dv_dy + v * drho_dy
            dG1 = rho * u * dv_dy + rho * v * du_dy + u * v * drho_dy
            dG2 = 2 * rho * v * dv_dy + v ** 2 * drho_dy + dp_dy
            dG3 = (dE_dy + dp_dy) * v + (E + p) * dv_dy

            flux_div = [dF0 + dG0, dF1 + dG1, dF2 + dG2, dF3 + dG3]
            source = [Sm, Sx, Sy, Se]

            for k in range(4):
                res = abs(source[k] - flux_div[k])
                if res > max_res:
                    max_res = res

    return max_res


# ===================================================================
# 5. Mesh generation and CI2 solution export
# ===================================================================

def generate_ci2_mesh():
    """Generate mesh from channel.geo, evaluate CI2 at nodes, write MSH."""
    # Mesh using gmsh CLI
    subprocess.run(
        ['gmsh', '/app/data/channel.geo', '-2', '-o', '/tmp/ci2_mesh.msh',
         '-format', 'msh2'],
        check=True, capture_output=True
    )

    # Read mesh
    mesh = meshio.read('/tmp/ci2_mesh.msh')
    pts = mesh.points[:, :2]
    n = len(pts)

    # Evaluate CI2 at each mesh node
    pressure = np.zeros(n)
    temperature = np.zeros(n)
    velocity_x = np.zeros(n)
    velocity_y = np.zeros(n)

    for i in range(n):
        result = ci2_evaluate(float(pts[i, 0]), float(pts[i, 1]))
        pressure[i] = result['pressure']
        temperature[i] = result['temperature']
        velocity_x[i] = result['velocity_x']
        velocity_y[i] = result['velocity_y']

    # Write mesh with embedded solution fields
    mesh.point_data = {
        'pressure': pressure,
        'temperature': temperature,
        'velocity_x': velocity_x,
        'velocity_y': velocity_y,
    }
    meshio.write('/app/results/ci2_solution.msh', mesh, file_format='gmsh22')


# ===================================================================
# Main
# ===================================================================

def main():
    results = {}

    # 1. Compressible flow
    results['compressible'] = {
        'normal_shock': normal_shock(1.5, 1.4),
        'isentropic': isentropic_relations(2.0, 1.4),
    }

    # 2. CI2 initial condition
    results['ci2'] = {
        'upstream_freestream': ci2_evaluate(0.05, 0.90),
        'downstream_postshock': ci2_evaluate(0.60, 0.50),
        'vortex_inner': ci2_evaluate(0.20, 0.55),
    }

    # 3. Convergence analysis
    data = load_convergence_data('/app/data/convergence_data.csv')
    results['convergence'] = analyze_convergence(data)

    # 4. MMS
    Sm, Sx, Sy, Se = mms_source_terms(0.25, 0.25)
    max_res = mms_verify_residual()

    results['mms'] = {
        'source_at_test_point': {
            'S_mass': Sm,
            'S_xmom': Sx,
            'S_ymom': Sy,
            'S_energy': Se,
        },
        'max_residual': max_res,
    }

    # Write JSON
    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/verification_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # 5. Generate mesh with CI2 solution
    generate_ci2_mesh()

    print("Verification pipeline complete.")


if __name__ == '__main__':
    main()
