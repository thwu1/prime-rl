#!/usr/bin/env python3

"""
FDS Heat Conduction Verification Framework

Parses FDS input files, computes analytical solutions for 1D transient
heat conduction (eigenvalue expansion), compares against simulation CSV
data, generates verification report and gnuplot plots.
"""

import csv
import json
import math
import os
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# FDS Input Parser
# ---------------------------------------------------------------------------

def parse_fds_input(filepath):
    """Parse an FDS input file and extract relevant parameters."""
    with open(filepath) as f:
        content = f.read()

    # Remove comments (lines starting with !)
    lines = []
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('!'):
            continue
        lines.append(line)
    content = '\n'.join(lines)

    # Extract namelist groups: &NAME ... /
    groups = re.findall(r'&(\w+)\s+(.*?)\s*/', content, re.DOTALL)

    result = {
        'materials': {},
        'surfaces': {},
        'devices': [],
        'time': {},
    }

    for gname, gbody in groups:
        gname = gname.upper()
        if gname == 'MATL':
            matl = _parse_namelist_params(gbody)
            matl_id = matl.get('ID', '').strip("'\"")
            result['materials'][matl_id] = {
                'conductivity': float(matl.get('CONDUCTIVITY', 0)),
                'specific_heat': float(matl.get('SPECIFIC_HEAT', 0)),  # kJ/(kg*K)
                'density': float(matl.get('DENSITY', 0)),
                'emissivity': float(matl.get('EMISSIVITY', 1.0)),
            }
        elif gname == 'SURF':
            surf = _parse_namelist_params(gbody)
            surf_id = surf.get('ID', '').strip("'\"")
            result['surfaces'][surf_id] = {
                'matl_id': surf.get('MATL_ID', '').strip("'\""),
                'tmp_gas_front': float(surf.get('TMP_GAS_FRONT', 20)),
                'thickness': float(surf.get('THICKNESS', 0)),
                'heat_transfer_coefficient': float(surf.get('HEAT_TRANSFER_COEFFICIENT', 0)),
                'backing': surf.get('BACKING', '').strip("'\""),
            }
        elif gname == 'DEVC':
            devc = _parse_namelist_params(gbody)
            dev_id = devc.get('ID', '').strip("'\"")
            depth = float(devc.get('DEPTH', 0))
            quantity = devc.get('QUANTITY', '').strip("'\"")
            result['devices'].append({
                'id': dev_id,
                'depth': depth,
                'quantity': quantity,
            })
        elif gname == 'TIME':
            time_params = _parse_namelist_params(gbody)
            result['time']['t_end'] = float(time_params.get('T_END', 0))
            result['time']['dt'] = float(time_params.get('DT', 1.0))

    return result


def _parse_namelist_params(body):
    """Parse Fortran namelist parameters from a body string."""
    params = {}
    # Normalize whitespace
    body = ' '.join(body.split())

    # Match patterns like KEY = VALUE or KEY=VALUE
    pattern = r"(\w+)\s*=\s*([^,=]+?)(?=\s+\w+\s*=|$)"
    matches = re.findall(pattern, body)

    for key, value in matches:
        params[key.upper()] = value.strip().rstrip(',')

    return params


# ---------------------------------------------------------------------------
# Eigenvalue Solver
# ---------------------------------------------------------------------------

def solve_eigenvalues(Bi, N=100):
    """
    Find first N positive roots of beta * tan(beta) = Bi.

    The roots lie in intervals:
      n=1: (0, pi/2)
      n>=2: ((n-1)*pi, (n-1)*pi + pi/2)
    """
    roots = []

    for n in range(1, N + 1):
        if n == 1:
            a = 1e-12
            b = math.pi / 2 - 1e-12
        else:
            a = (n - 1) * math.pi + 1e-12
            b = (n - 1) * math.pi + math.pi / 2 - 1e-12

        def f(beta):
            return beta * math.tan(beta) - Bi

        # Bisection method
        fa = f(a)
        for _ in range(200):
            mid = (a + b) / 2
            fm = f(mid)
            if abs(fm) < 1e-15 or (b - a) < 1e-15:
                break
            if fa * fm < 0:
                b = mid
            else:
                a = mid
                fa = f(a)

        roots.append((a + b) / 2)

    return roots


# ---------------------------------------------------------------------------
# Analytical Solution
# ---------------------------------------------------------------------------

def analytical_temperature(x, t, T_inf, T_i, L, alpha, eigenvalues):
    """
    Compute analytical temperature for 1D conduction in a slab.

    Geometry:
      x=0: insulated face (dT/dx = 0)
      x=L: convective face (-k dT/dx = h(T - T_inf))

    Solution:
      T(x,t) = T_inf + (T_i - T_inf) * sum C_n * cos(beta_n * x/L) * exp(-beta_n^2 * Fo)

    where:
      Fo = alpha * t / L^2
      C_n = 4 * sin(beta_n) / (2*beta_n + sin(2*beta_n))
    """
    if t <= 0:
        return T_i

    Fo = alpha * t / (L * L)
    theta_ratio = 0.0

    for beta_n in eigenvalues:
        C_n = 4.0 * math.sin(beta_n) / (2.0 * beta_n + math.sin(2.0 * beta_n))
        theta_ratio += C_n * math.cos(beta_n * x / L) * math.exp(-beta_n**2 * Fo)

    return T_inf + (T_i - T_inf) * theta_ratio


# ---------------------------------------------------------------------------
# CSV Data Reader
# ---------------------------------------------------------------------------

def read_simulation_csv(filepath):
    """Read FDS device output CSV file."""
    data = []
    headers = None
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            if headers is None:
                headers = [h.strip() for h in row]
                continue
            data.append([float(v) for v in row])
    return headers, data


# ---------------------------------------------------------------------------
# Device-to-coordinate mapping
# ---------------------------------------------------------------------------

def device_x_position(device_id, L):
    """
    Map FDS device ID to x-coordinate (from insulated face).

    FDS devices report depth from the convective (front) face.
    x (from insulated face) = L - depth
    """
    mapping = {
        'T_back': 0.0,           # insulated face = x=0
        'T_d08': L - 0.08,      # depth 0.08 from front -> x = L-0.08 = 0.02
        'T_d06': L - 0.06,      # depth 0.06 from front -> x = L-0.06 = 0.04
        'T_d04': L - 0.04,      # depth 0.04 from front -> x = L-0.04 = 0.06
        'T_d02': L - 0.02,      # depth 0.02 from front -> x = L-0.02 = 0.08
        'T_front': L,            # convective face = x=L
    }
    return mapping.get(device_id, None)


# ---------------------------------------------------------------------------
# Gnuplot Plot Generation
# ---------------------------------------------------------------------------

def generate_gnuplot_plot(case_name, sim_headers, sim_data, analytical_temps,
                          Bi, plots_dir):
    """Generate a gnuplot verification plot comparing sim vs analytical."""
    os.makedirs(plots_dir, exist_ok=True)

    device_names = sim_headers[1:]  # skip time column

    # Write simulation data CSV for gnuplot
    sim_csv = os.path.join(plots_dir, f'{case_name}_sim.csv')
    with open(sim_csv, 'w') as f:
        f.write(' '.join(sim_headers) + '\n')
        for row in sim_data:
            f.write(' '.join(f'{v:.4f}' for v in row) + '\n')

    # Write analytical data CSV for gnuplot
    anal_csv = os.path.join(plots_dir, f'{case_name}_anal.csv')
    with open(anal_csv, 'w') as f:
        f.write(' '.join(sim_headers) + '\n')
        for i, row in enumerate(sim_data):
            t = row[0]
            vals = [f'{t:.4f}']
            for dev_name in device_names:
                vals.append(f'{analytical_temps[dev_name][i]:.4f}')
            f.write(' '.join(vals) + '\n')

    # Build gnuplot script
    png_path = os.path.join(plots_dir, f'{case_name}.png')
    gp_script = os.path.join(plots_dir, f'{case_name}.gp')

    lines = []
    lines.append(f"set terminal pngcairo enhanced size 1200,800 font 'DejaVuSans,11'")
    lines.append(f"set output '{png_path}'")
    lines.append(f"set xlabel 'Time (s)'")
    lines.append(f"set ylabel 'Temperature (C)'")
    lines.append(f"set title '{case_name} - Verification (Bi={Bi:.2f})'")
    lines.append(f"set key outside right top")
    lines.append(f"set grid")

    plot_cmds = []
    for j, dev in enumerate(device_names):
        col = j + 2  # 1-indexed gnuplot columns
        plot_cmds.append(
            f"'{sim_csv}' using 1:{col} with points pt 7 ps 0.8 "
            f"title '{dev} (sim)'"
        )
        plot_cmds.append(
            f"'{anal_csv}' using 1:{col} with lines lw 2 "
            f"title '{dev} (anal)'"
        )

    lines.append('plot ' + ', \\\n     '.join(plot_cmds))

    with open(gp_script, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    # Execute gnuplot
    subprocess.run(['gnuplot', gp_script], check=True)
    print(f"  Plot written to {png_path}")


# ---------------------------------------------------------------------------
# Main Verification
# ---------------------------------------------------------------------------

def verify_case(case_name, input_dir, data_dir, tolerance, plots_dir):
    """Run verification for a single case."""

    fds_path = os.path.join(input_dir, f'{case_name}.fds')
    csv_path = os.path.join(data_dir, f'{case_name}_devc.csv')

    # Parse FDS input
    fds_data = parse_fds_input(fds_path)

    # Extract parameters from first surface/material pair
    surf = list(fds_data['surfaces'].values())[0]
    matl_id = surf['matl_id']
    matl = fds_data['materials'][matl_id]

    k = matl['conductivity']           # W/(m*K)
    cp_kJ = matl['specific_heat']      # kJ/(kg*K) in FDS
    cp = cp_kJ * 1000.0               # Convert to J/(kg*K)
    rho = matl['density']              # kg/m^3
    h = surf['heat_transfer_coefficient']  # W/(m^2*K)
    L = surf['thickness']              # m
    T_inf = surf['tmp_gas_front']      # deg C
    T_i = 20.0                         # Initial temperature (standard assumption)

    alpha = k / (rho * cp)             # m^2/s
    Bi = h * L / k                     # Biot number

    # Solve eigenvalue equation
    N_eigenvalues = 100
    eigenvalues = solve_eigenvalues(Bi, N_eigenvalues)

    # Read simulation data
    headers, sim_data = read_simulation_csv(csv_path)
    device_names = headers[1:]  # Skip time column

    # Compute errors at each device and time point
    device_errors = {}
    analytical_temps = {}  # for plotting
    max_abs_error_overall = 0.0
    max_rel_error_overall = 0.0

    for dev_name in device_names:
        dev_idx = headers.index(dev_name)
        x = device_x_position(dev_name, L)
        if x is None:
            continue

        max_abs = 0.0
        max_rel = 0.0
        anal_temps_dev = []

        for row in sim_data:
            t = row[0]
            T_sim = row[dev_idx]
            T_anal = analytical_temperature(x, t, T_inf, T_i, L, alpha, eigenvalues)
            anal_temps_dev.append(T_anal)

            abs_err = abs(T_sim - T_anal)
            # Relative error based on temperature deviation from initial
            theta = abs(T_anal - T_i)
            if theta > 1.0:  # Only compute relative error where deviation is significant
                rel_err = abs_err / theta
            else:
                rel_err = 0.0

            max_abs = max(max_abs, abs_err)
            max_rel = max(max_rel, rel_err)

        analytical_temps[dev_name] = anal_temps_dev

        device_errors[dev_name] = {
            'max_absolute_error': round(max_abs, 6),
            'max_relative_error': round(max_rel, 6),
        }

        max_abs_error_overall = max(max_abs_error_overall, max_abs)
        max_rel_error_overall = max(max_rel_error_overall, max_rel)

    # Generate gnuplot plot
    generate_gnuplot_plot(case_name, headers, sim_data, analytical_temps,
                          Bi, plots_dir)

    # Determine pass/fail
    rel_threshold = tolerance
    status = "PASS" if max_rel_error_overall < rel_threshold else "FAIL"

    return {
        'biot_number': round(Bi, 4),
        'eigenvalues': [round(e, 10) for e in eigenvalues[:5]],
        'max_absolute_error': round(max_abs_error_overall, 6),
        'max_relative_error': round(max_rel_error_overall, 6),
        'status': status,
        'device_errors': device_errors,
    }


def main():
    config_path = '/app/config.json'
    with open(config_path) as f:
        config = json.load(f)

    input_dir = config['input_dir']
    data_dir = config['data_dir']
    output_file = config['output_file']
    tolerance = config['relative_error_threshold']
    plots_dir = config['plots_dir']
    case_names = config['cases']

    report = {
        'cases': {},
        'tolerance': tolerance,
        'overall_status': 'PASS',
        'pass_count': 0,
        'fail_count': 0,
    }

    for case_name in case_names:
        print(f"Verifying {case_name}...")
        case_result = verify_case(case_name, input_dir, data_dir, tolerance,
                                  plots_dir)
        report['cases'][case_name] = case_result

        if case_result['status'] == 'PASS':
            report['pass_count'] += 1
        else:
            report['fail_count'] += 1
            report['overall_status'] = 'FAIL'

        print(f"  Bi={case_result['biot_number']}, "
              f"max_rel_err={case_result['max_relative_error']:.6f}, "
              f"status={case_result['status']}")

    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {output_file}")
    print(f"Overall: {report['pass_count']} PASS, {report['fail_count']} FAIL")


if __name__ == '__main__':
    main()
