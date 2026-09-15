#!/usr/bin/env python3
"""
Complete convergence study runner.

Fixes gmsh script, generates meshes, runs solver, computes errors,
produces gnuplot convergence plot, and writes results.json.
"""
import subprocess
import json
import numpy as np
import sys
import os

sys.path.insert(0, '/app')


def fix_geo_file():
    """Fix the two bugs in the gmsh .geo script."""
    geo_path = '/app/mesh_template.geo'
    with open(geo_path) as f:
        content = f.read()

    # Fix 1: Transfinite needs N+1 nodes for N cells
    content = content.replace(
        'Transfinite Curve {1} = N;',
        'Transfinite Curve {1} = N + 1;'
    )

    # Fix 2: Use msh2 format (compatible with our parser)
    content = content.replace(
        'Mesh.MshFileVersion = 4.1;',
        'Mesh.MshFileVersion = 2.2;'
    )

    # Add Physical Curve for proper element export
    content = content.replace(
        'Mesh 1;',
        'Physical Curve("tube") = {1};\n\nMesh 1;'
    )

    with open(geo_path, 'w') as f:
        f.write(content)


def generate_mesh(N):
    """Generate 1D mesh with N cells using gmsh CLI."""
    msh_path = f'/app/mesh_N{N}.msh'
    cmd = [
        'gmsh', '-1', '/app/mesh_template.geo',
        '-setnumber', 'N', str(N),
        '-o', msh_path,
        '-format', 'msh2'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gmsh failed for N={N}: {result.stderr}")
    return msh_path


def compute_l2_error(x_num, rho_num, x_exact, rho_exact):
    """Compute L2 error norm between numerical and exact density profiles."""
    rho_exact_interp = np.interp(x_num, x_exact, rho_exact)
    dx = (x_num[-1] - x_num[0]) / len(x_num)
    return np.sqrt(dx * np.sum((rho_num - rho_exact_interp) ** 2))


def write_gnuplot_script():
    """Write a complete gnuplot script for the convergence plot."""
    script = (
        "set terminal pngcairo size 800,600 enhanced\n"
        "set output '/app/convergence.png'\n"
        "set xlabel 'Number of cells (N)'\n"
        "set ylabel 'L2 error (density)'\n"
        "set title 'Grid Convergence Study - 1D Euler Equations'\n"
        "set logscale xy\n"
        "set grid\n"
        "set key top right\n"
        "plot '/app/convergence_data.dat' using 1:2 with linespoints "
        "pt 7 ps 1.5 lw 2 title 'Computed L2 error'\n"
        "set output\n"
    )
    with open('/app/plot_convergence.gp', 'w') as f:
        f.write(script)


def main():
    with open('/app/problem_config.json') as f:
        config = json.load(f)

    from euler_solver import solve
    from exact_riemann import exact_riemann

    # Fix the gmsh geometry script
    fix_geo_file()

    # Compute exact solution on fine grid
    x_fine = np.linspace(config['domain']['x_left'], config['domain']['x_right'], 10000)
    rho_exact, u_exact, p_exact, p_star, u_star = exact_riemann(
        config['left_state']['rho'], config['left_state']['u'], config['left_state']['p'],
        config['right_state']['rho'], config['right_state']['u'], config['right_state']['p'],
        config['gamma'], x_fine, config['t_end'], config['domain']['x_diaphragm']
    )

    # Run solver at each resolution
    resolutions = [100, 200, 400, 800]
    errors = {}

    for N in resolutions:
        msh_path = generate_mesh(N)
        x_num, rho_num, u_num, p_num = solve(config, msh_path)
        l2_err = compute_l2_error(x_num, rho_num, x_fine, rho_exact)
        errors[N] = l2_err
        print(f"N={N}: L2 error = {l2_err:.6e}")

    # Write convergence data for gnuplot
    with open('/app/convergence_data.dat', 'w') as f:
        f.write('# N    L2_error\n')
        for N in resolutions:
            f.write(f'{N}    {errors[N]:.8e}\n')

    # Convergence order via Richardson extrapolation (using finest grid pair)
    r = 2.0
    e_med, e_fine = errors[400], errors[800]
    conv_order = np.log(e_med / e_fine) / np.log(r)

    # GCI (Roache's method, Fs = 1.25)
    Fs = 1.25
    rel_err = abs(e_med - e_fine) / e_fine
    gci_finest = Fs * rel_err / (r ** conv_order - 1.0)

    # Wave speeds and star-region densities
    gamma = config['gamma']
    rho_L = config['left_state']['rho']
    u_L_val = config['left_state']['u']
    p_L = config['left_state']['p']
    rho_R = config['right_state']['rho']
    u_R_val = config['right_state']['u']
    p_R = config['right_state']['p']

    a_L = np.sqrt(gamma * p_L / rho_L)
    a_R = np.sqrt(gamma * p_R / rho_R)
    g1 = (gamma - 1.0) / (2.0 * gamma)
    g2 = (gamma + 1.0) / (2.0 * gamma)
    g6 = (gamma - 1.0) / (gamma + 1.0)

    a_star_L = a_L * (p_star / p_L) ** g1
    S_HL = u_L_val - a_L
    S_TL = u_star - a_star_L
    rho_star_L = rho_L * (p_star / p_L) ** (1.0 / gamma)

    S_R = u_R_val + a_R * np.sqrt(g2 * p_star / p_R + g1)
    rho_star_R = rho_R * ((p_star / p_R + g6) / (g6 * p_star / p_R + 1.0))

    results = {
        'p_star': float(p_star),
        'u_star': float(u_star),
        'rho_star_L': float(rho_star_L),
        'rho_star_R': float(rho_star_R),
        'shock_speed': float(S_R),
        'contact_speed': float(u_star),
        'rarefaction_head_speed': float(S_HL),
        'rarefaction_tail_speed': float(S_TL),
        'convergence_order': float(conv_order),
        'gci_finest': float(gci_finest),
        'l2_error_density_N100': float(errors[100]),
        'l2_error_density_N200': float(errors[200]),
        'l2_error_density_N400': float(errors[400]),
        'l2_error_density_N800': float(errors[800]),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Generate and run gnuplot script
    write_gnuplot_script()
    subprocess.run(['gnuplot', '/app/plot_convergence.gp'], check=True)

    print("Done. Results at /app/results.json, plot at /app/convergence.png")


if __name__ == '__main__':
    main()
