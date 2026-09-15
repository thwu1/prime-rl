#!/usr/bin/env python3
"""
Dakota-compatible cantilever beam simulation driver.
Implements Dakota's standard file-based I/O protocol for fork interface.

Usage: python3 cantilever_driver.py <params_file> <results_file>

Responses (3 functions):
  f0: area = w * t
  f1: stress_con = stress/R - 1  (stress constraint, <= 0 feasible)
  f2: disp_con = D/D0 - 1  (displacement constraint, <= 0 feasible)

Supports ASV flags: 1 (value), 2 (gradient), 3 (value+gradient).
Gradients computed analytically w.r.t. derivative variables in DVV.
"""

import sys
import math

L = 100.0
D0 = 2.2535


def main():
    params_file = sys.argv[1]
    results_file = sys.argv[2]

    with open(params_file) as f:
        lines = f.readlines()

    idx = 0

    # --- Parse variables ---
    parts = lines[idx].split()
    num_vars = int(parts[0])
    idx += 1

    var_values = {}
    var_labels = []
    for _ in range(num_vars):
        parts = lines[idx].split()
        val = float(parts[0])
        label = parts[1].lower()
        var_values[label] = val
        var_labels.append(label)
        idx += 1

    # --- Parse ASV ---
    parts = lines[idx].split()
    num_fns = int(parts[0])
    idx += 1

    asv = []
    for _ in range(num_fns):
        parts = lines[idx].split()
        asv.append(int(parts[0]))
        idx += 1

    # --- Parse DVV ---
    parts = lines[idx].split()
    num_deriv_vars = int(parts[0])
    idx += 1

    dvv = []
    for _ in range(num_deriv_vars):
        parts = lines[idx].split()
        dvv_idx = int(parts[0]) - 1  # 1-based to 0-based
        dvv.append(var_labels[dvv_idx])
        idx += 1

    # --- Extract variable values (handle 4-var and 6-var cases) ---
    w = var_values.get('w', 2.5)
    t = var_values.get('t', 2.5)
    r = var_values['r']
    e = var_values['e']
    x = var_values['x']
    y = var_values['y']

    # --- Derived quantities ---
    area = w * t
    w_sq = w * w
    t_sq = t * t
    r_sq = r * r
    x_sq = x * x
    y_sq = y * y

    stress = 600.0 * y / (w * t_sq) + 600.0 * x / (w_sq * t)

    D2 = (y / t_sq) ** 2 + (x / w_sq) ** 2
    sqrt_D2 = math.sqrt(D2) if D2 > 0 else 1e-30
    D1 = 4.0 * L ** 3 / (e * area)
    D4 = D1 * sqrt_D2 / D0
    D3 = D1 / (sqrt_D2 * D0)

    # --- Response structure ---
    if num_fns == 2:
        objective = False
        c1i, c2i = 0, 1
    else:
        objective = True
        c1i, c2i = 1, 2

    # --- Write results ---
    with open(results_file, 'w') as fout:
        fout.flush()

        # f0: area (objective)
        if objective:
            if asv[0] & 1:
                fout.write(f"  {area:20.15e}\n")
            if asv[0] & 2:
                grad = []
                for dv in dvv:
                    if dv == 'w':
                        grad.append(t)
                    elif dv == 't':
                        grad.append(w)
                    else:
                        grad.append(0.0)
                fout.write("[ " + " ".join(f"{g:20.15e}" for g in grad) + " ]\n")

        # f1: stress constraint = stress/R - 1
        if asv[c1i] & 1:
            fout.write(f"  {stress / r - 1.0:20.15e}\n")
        if asv[c1i] & 2:
            grad = []
            for dv in dvv:
                if dv == 'w':
                    grad.append(-600.0 * (y / t + 2.0 * x / w) / (w_sq * t * r))
                elif dv == 't':
                    grad.append(-600.0 * (2.0 * y / t + x / w) / (w * t_sq * r))
                elif dv == 'r':
                    grad.append(-stress / r_sq)
                elif dv == 'e':
                    grad.append(0.0)
                elif dv == 'x':
                    grad.append(600.0 / (w_sq * t * r))
                elif dv == 'y':
                    grad.append(600.0 / (w * t_sq * r))
                else:
                    grad.append(0.0)
            fout.write("[ " + " ".join(f"{g:20.15e}" for g in grad) + " ]\n")

        # f2: displacement constraint = D/D0 - 1
        if asv[c2i] & 1:
            fout.write(f"  {D4 - 1.0:20.15e}\n")
        if asv[c2i] & 2:
            grad = []
            for dv in dvv:
                if dv == 'w':
                    grad.append(-D3 * 2.0 * x_sq / (w_sq * w_sq * w) - D4 / w)
                elif dv == 't':
                    grad.append(-D3 * 2.0 * y_sq / (t_sq * t_sq * t) - D4 / t)
                elif dv == 'r':
                    grad.append(0.0)
                elif dv == 'e':
                    grad.append(-D4 / e)
                elif dv == 'x':
                    grad.append(D3 * x / (w_sq * w_sq))
                elif dv == 'y':
                    grad.append(D3 * y / (t_sq * t_sq))
                else:
                    grad.append(0.0)
            fout.write("[ " + " ".join(f"{g:20.15e}" for g in grad) + " ]\n")


if __name__ == "__main__":
    main()
