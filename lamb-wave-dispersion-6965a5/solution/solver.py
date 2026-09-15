#!/usr/bin/env python3
"""
Lamb wave dispersion curve solver using the Stiffness Matrix Method (SMM)
for multilayered anisotropic plates — decoupled case only.

References:
  [1] Nayfeh, JASA 89(4), 1521-1531 (1991).
  [2] Rokhlin & Wang, JASA 112(3), 822-834 (2002).
  [3] Huber, JASA 154(2), 1073-1094 (2023).

"""

import numpy as np
from scipy.optimize import minimize_scalar
import yaml
import json
import argparse
import sys
import os


# ───────────────────────── configuration ──────────────────────────────────

def parse_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def build_layup(cfg):
    """Expand super-layer → full layer stack.  Returns (orientations, thicknesses_m, total_mm)."""
    orientations = cfg['layup']['orientations']
    thicknesses = cfg['layup']['thicknesses']
    reps = cfg['layup']['repetitions']
    symmetric = cfg['layup']['symmetric']
    prop_angle = cfg['propagation_angle']

    # Validate decoupled condition
    for orient in orientations:
        beta = (orient - prop_angle) % 180
        if beta != 0 and beta != 90:
            print(
                f"Error: layer orientation {orient}° with propagation angle "
                f"{prop_angle}° gives beta={beta}°, which is not 0° or 90°. "
                "Only the decoupled Lamb case is supported.",
                file=sys.stderr,
            )
            sys.exit(1)

    full_orient = list(orientations) * reps
    full_thick = list(thicknesses) * reps

    if symmetric:
        full_orient = full_orient + full_orient[::-1]
        full_thick = full_thick + full_thick[::-1]

    full_thick_m = [t / 1e3 for t in full_thick]
    total_mm = sum(full_thick)
    return full_orient, full_thick_m, total_mm


# ──────────────────── stiffness tensor rotation ───────────────────────────

def rotate_stiffness(C_GPa, angle_deg, prop_angle_deg):
    """Rotate orthotropic stiffness (Voigt) for decoupled Lamb. Returns Pa dict."""
    beta = angle_deg - prop_angle_deg
    s = np.sin(np.radians(beta))
    g = np.cos(np.radians(beta))

    C11 = C_GPa['C11'] * 1e9
    C12 = C_GPa['C12'] * 1e9
    C13 = C_GPa['C13'] * 1e9
    C22 = C_GPa['C22'] * 1e9
    C23 = C_GPa['C23'] * 1e9
    C33 = C_GPa['C33'] * 1e9
    C44 = C_GPa['C44'] * 1e9
    C55 = C_GPa['C55'] * 1e9
    C66 = C_GPa['C66'] * 1e9

    return {
        11: C11 * g**4 + C22 * s**4 + 2 * (C12 + 2 * C66) * s**2 * g**2,
        13: C13 * g**2 + C23 * s**2,
        33: C33,
        55: C55 * g**2 + C44 * s**2,
    }


# ──────────── vectorised SMM determinant at one frequency ─────────────────

def _batch_inv_2x2(M):
    """Invert (N,2,2) array using explicit formula — never raises LinAlgError."""
    a, b = M[:, 0, 0], M[:, 0, 1]
    c, d = M[:, 1, 0], M[:, 1, 1]
    det = a * d - b * c
    det = np.where(np.abs(det) < 1e-30, 1e-30, det)
    out = np.empty_like(M)
    out[:, 0, 0] = d / det
    out[:, 0, 1] = -b / det
    out[:, 1, 0] = -c / det
    out[:, 1, 1] = a / det
    return out


def compute_det_at_frequency(omega, cp_arr, layers_c, layers_thick, density):
    """
    Compute |det(K_global)| for an array of phase velocities at fixed omega.

    cp_arr : 1-D array of phase velocities in m/s
    Returns: 1-D array of |det| values (same length as cp_arr).
    """
    N = len(cp_arr)
    EPS = 1e-30  # regularisation

    k = omega / cp_arr                       # (N,)
    k2 = k ** 2
    k4 = k2 ** 2
    rw2 = density * omega ** 2               # scalar

    # Build layer stiffness matrices  ──────────────────────────────────────
    L_mats = []
    for c, th in zip(layers_c, layers_thick):
        A1 = 2.0 * c[33] * c[55]

        a21 = c[11] * c[33] - 2.0 * c[13] * c[55] - c[13] ** 2
        a22 = -(c[33] + c[55])
        a31 = c[11] * c[55]
        a32 = -(c[11] + c[55])

        A2 = a21 * k2 + a22 * rw2
        A3 = a31 * k4 + a32 * rw2 * k2 + rw2 ** 2

        disc = A2 ** 2 - 2.0 * A1 * A3
        sd = np.lib.scimath.sqrt(disc)

        k32_1 = (sd - A2) / A1
        k32_2 = (-sd - A2) / A1
        k3_1 = np.lib.scimath.sqrt(k32_1)
        k3_2 = np.lib.scimath.sqrt(k32_2)

        # Polarisation W  [3], Eq. (39)
        d1 = (c[13] + c[55]) * k * k3_1
        d2 = (c[13] + c[55]) * k * k3_2
        d1 = np.where(np.abs(d1) < EPS, EPS, d1)
        d2 = np.where(np.abs(d2) < EPS, EPS, d2)
        W1 = (rw2 - c[11] * k2 - c[55] * k32_1) / d1
        W2 = (rw2 - c[11] * k2 - c[55] * k32_2) / d2

        # Stress amplitudes  [3], Eq. (40)
        D3_1 = 1j * (c[13] * k + c[33] * k3_1 * W1)
        D3_2 = 1j * (c[13] * k + c[33] * k3_2 * W2)
        D5_1 = 1j * c[55] * (k3_1 + k * W1)
        D5_2 = 1j * c[55] * (k3_2 + k * W2)

        # Exponential  [3], Eqs. (41)-(42)
        E1 = np.exp(1j * k3_1 * th)
        E2 = np.exp(1j * k3_2 * th)

        # ---- assemble 4×4 L1, L2 matrices (batched: N×4×4)  [3], Eq. (21)
        L1 = np.zeros((N, 4, 4), dtype=complex)
        L1[:, 0, 0] = D3_1;      L1[:, 0, 1] = D3_2
        L1[:, 0, 2] = D3_1 * E1; L1[:, 0, 3] = D3_2 * E2
        L1[:, 1, 0] = D5_1;      L1[:, 1, 1] = D5_2
        L1[:, 1, 2] = -D5_1*E1;  L1[:, 1, 3] = -D5_2*E2
        L1[:, 2, 0] = D3_1 * E1; L1[:, 2, 1] = D3_2 * E2
        L1[:, 2, 2] = D3_1;      L1[:, 2, 3] = D3_2
        L1[:, 3, 0] = D5_1 * E1; L1[:, 3, 1] = D5_2 * E2
        L1[:, 3, 2] = -D5_1;     L1[:, 3, 3] = -D5_2

        L2 = np.zeros((N, 4, 4), dtype=complex)
        L2[:, 0, 0] = 1;          L2[:, 0, 1] = 1
        L2[:, 0, 2] = E1;         L2[:, 0, 3] = E2
        L2[:, 1, 0] = W1;         L2[:, 1, 1] = W2
        L2[:, 1, 2] = -W1 * E1;   L2[:, 1, 3] = -W2 * E2
        L2[:, 2, 0] = E1;         L2[:, 2, 1] = E2
        L2[:, 2, 2] = 1;          L2[:, 2, 3] = 1
        L2[:, 3, 0] = W1 * E1;    L2[:, 3, 1] = W2 * E2
        L2[:, 3, 2] = -W1;        L2[:, 3, 3] = -W2

        # L = L1 @ inv(L2) — batch solve via transpose trick
        L2 += EPS * np.eye(4)[np.newaxis, :, :]
        try:
            L = np.linalg.solve(
                L2.transpose(0, 2, 1), L1.transpose(0, 2, 1)
            ).transpose(0, 2, 1)
        except np.linalg.LinAlgError:
            # Fallback: per-element solve
            L = np.full((N, 4, 4), 1e30 + 0j, dtype=complex)
            for ii in range(N):
                try:
                    L[ii] = np.linalg.solve(L2[ii].T, L1[ii].T).T
                except np.linalg.LinAlgError:
                    pass  # leave as sentinel
        L_mats.append(L)

    # Recursive SMM assembly  [2], Eq. (21) ───────────────────────────────
    M = L_mats[0].copy()
    for Lm in L_mats[1:]:
        M0 = Lm[:, :2, :2] - M[:, 2:, 2:]
        M0inv = _batch_inv_2x2(M0)
        M1 = M[:, :2, 2:] @ M0inv
        M2 = Lm[:, 2:, :2] @ M0inv
        Mn = np.empty_like(M)
        Mn[:, :2, :2] = M[:, :2, :2] + M1 @ M[:, 2:, :2]
        Mn[:, :2, 2:] = -(M1 @ Lm[:, :2, 2:])
        Mn[:, 2:, :2] = M2 @ M[:, 2:, :2]
        Mn[:, 2:, 2:] = Lm[:, 2:, 2:] - M2 @ Lm[:, :2, 2:]
        M = Mn

    det_vals = np.abs(np.linalg.det(M))

    # Replace NaN / Inf with large sentinel
    bad = ~np.isfinite(det_vals)
    if np.any(bad):
        det_vals[bad] = np.nanmax(det_vals[~bad]) if np.any(~bad) else 1e30

    return det_vals


# ───────────────────── root finding / refinement ──────────────────────────

def find_local_minima(det_vals, cp_arr_mms):
    """Return list of (cp_m_per_ms, grid_index) for local minima in |det|."""
    log_d = np.log10(np.maximum(det_vals, 1e-300))
    hits = []
    for i in range(2, len(log_d) - 2):
        if log_d[i] < log_d[i - 1] and log_d[i] < log_d[i + 1]:
            nb = det_vals[max(0, i - 8): min(len(det_vals), i + 9)]
            nb_med = np.median(nb)
            if det_vals[i] < 0.1 * nb_med and nb_med > 0:
                hits.append((cp_arr_mms[i], i))
    return hits


def refine_root(cp_lo_ms, cp_hi_ms, omega, layers_c, layers_thick, density):
    """Refine a root bracket using bounded minimisation. Returns (cp_m_s, det)."""
    def obj(cp):
        return compute_det_at_frequency(
            omega, np.array([cp]), layers_c, layers_thick, density
        )[0]

    res = minimize_scalar(
        obj, bounds=(cp_lo_ms, cp_hi_ms), method='bounded',
        options={'xatol': 1.0},  # 1 m/s accuracy
    )
    return res.x, res.fun


# ────────────────────── mode tracking ─────────────────────────────────────

def track_modes(all_roots, freqs, num_modes):
    """
    Match roots across frequencies by nearest-neighbour continuity.
    Returns list of mode dicts with 'index', 'phase_velocity', 'group_velocity'.
    """
    slots = {m: [] for m in range(num_modes)}

    for fi, (f, roots) in enumerate(zip(freqs, all_roots)):
        if not roots:
            continue

        # If no modes started yet, initialise from first roots
        if all(len(slots[m]) == 0 for m in range(num_modes)):
            for m in range(min(num_modes, len(roots))):
                slots[m].append((f, roots[m]))
            continue

        available = list(range(len(roots)))

        # Match to existing modes (by closest cp)
        for m in range(num_modes):
            if not slots[m]:
                continue
            last_cp = slots[m][-1][1]
            best_j, best_d = None, float('inf')
            for j in available:
                d = abs(roots[j] - last_cp)
                if d < best_d:
                    best_d, best_j = d, j
            if best_j is not None and best_d < 2.0:  # max 2 km/s jump
                slots[m].append((f, roots[best_j]))
                available.remove(best_j)

        # Assign remaining roots to empty slots (new modes appearing)
        for j in available:
            for m in range(num_modes):
                if not slots[m]:
                    slots[m].append((f, roots[j]))
                    break

    # Package into output dicts
    result = []
    for m in range(num_modes):
        pts = slots[m]
        if len(pts) >= 5:
            result.append({
                'index': 0,
                'phase_velocity': [[float(f), float(round(cp, 6))] for f, cp in pts],
                'group_velocity': [],
            })

    # Sort by ascending cp at first data point
    result.sort(key=lambda x: x['phase_velocity'][0][1])
    for i, mode in enumerate(result):
        mode['index'] = i

    return result


# ───────────────────── group velocity ─────────────────────────────────────

def add_group_velocity(modes):
    """Compute cg = cp^2 / (cp - f * dcp/df) via smoothed numerical differentiation."""
    for mode in modes:
        pv = mode['phase_velocity']
        if len(pv) < 5:
            mode['group_velocity'] = []
            continue

        farr = np.array([p[0] for p in pv])
        cparr = np.array([p[1] for p in pv])

        # Smooth phase velocity curve before differentiation to suppress
        # numerical noise that produces unphysical group velocity spikes
        # near mode cutoff frequencies or rapid dispersion regions.
        n = len(cparr)
        smooth = np.copy(cparr)
        if n >= 11:
            # 5-point moving average for interior points
            for i in range(2, n - 2):
                smooth[i] = np.mean(cparr[i-2:i+3])
        elif n >= 7:
            # 3-point moving average
            for i in range(1, n - 1):
                smooth[i] = np.mean(cparr[i-1:i+2])

        dcpdf = np.gradient(smooth, farr)
        denom = cparr - farr * dcpdf

        with np.errstate(divide='ignore', invalid='ignore'):
            cg = cparr ** 2 / denom

        # Physical upper bound: for the materials in these configs, no Lamb
        # wave group velocity should exceed the longitudinal bulk velocity
        # by a large factor.  Values above ~12 km/s are numerical artifacts
        # from finite-difference noise near steep dispersion regions.
        CG_UPPER = 14.5

        gv = []
        for j in range(len(farr)):
            if np.isfinite(cg[j]) and 0 < cg[j] < CG_UPPER:
                gv.append([float(farr[j]), float(round(cg[j], 6))])
        mode['group_velocity'] = gv


# ────────────────────── main solver ───────────────────────────────────────

def solve_dispersion(cfg):
    mat = cfg['material']
    density = mat['density']
    C_GPa = mat['stiffness_GPa']
    prop_angle = cfg['propagation_angle']
    analysis = cfg['analysis']

    orientations, thicknesses_m, total_mm = build_layup(cfg)
    num_layers = len(orientations)

    # Pre-compute rotated stiffnesses for each layer
    layers_c = [
        rotate_stiffness(C_GPa, orient, prop_angle)
        for orient in orientations
    ]

    freq_min = analysis['frequency_min']
    freq_max = analysis['frequency_max']
    freq_steps = analysis['frequency_steps']
    num_modes = analysis['num_modes']
    cp_max = analysis['phase_velocity_max']
    cp_steps = analysis['phase_velocity_steps']

    freqs = np.linspace(freq_min, freq_max, freq_steps)
    cp_min_ms = 0.2    # km/s lower bound
    cp_arr_ms = np.linspace(cp_min_ms * 1e3, cp_max * 1e3, cp_steps)   # m/s
    cp_arr_mms = cp_arr_ms / 1e3   # m/ms (= km/s)

    all_roots = []   # list of sorted cp lists (m/ms) per frequency

    for f_kHz in freqs:
        omega = 2.0 * np.pi * f_kHz * 1e3

        det_vals = compute_det_at_frequency(
            omega, cp_arr_ms, layers_c, thicknesses_m, density
        )

        raw_hits = find_local_minima(det_vals, cp_arr_mms)

        refined = []
        for cp_approx_mms, idx in raw_hits:
            lo = cp_arr_ms[max(0, idx - 3)]
            hi = cp_arr_ms[min(cp_steps - 1, idx + 3)]
            try:
                cp_ref_ms, det_ref = refine_root(
                    lo, hi, omega, layers_c, thicknesses_m, density
                )
                refined.append(cp_ref_ms / 1e3)   # -> m/ms
            except Exception:
                refined.append(cp_approx_mms)

        # De-duplicate within 0.05 km/s
        refined.sort()
        deduped = []
        for r in refined:
            if not deduped or abs(r - deduped[-1]) > 0.05:
                deduped.append(r)

        all_roots.append(deduped)

    modes = track_modes(all_roots, freqs.tolist(), num_modes)
    add_group_velocity(modes)

    return {
        'metadata': {
            'material': mat['name'],
            'total_thickness_mm': total_mm,
            'num_layers': num_layers,
            'method': 'SMM',
            'propagation_angle_deg': prop_angle,
        },
        'modes': modes,
    }


# ────────────────────── CLI entry point ───────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Lamb wave dispersion solver (SMM, decoupled case)'
    )
    parser.add_argument('config', help='YAML configuration file')
    parser.add_argument('-o', '--output', required=True, help='Output JSON path')
    args = parser.parse_args()

    cfg = parse_config(args.config)
    result = solve_dispersion(cfg)

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    n_modes = len(result['modes'])
    name = result['metadata']['material']
    print(f"Computed {n_modes} modes for {name}")
    print(f"Output written to {args.output}")


if __name__ == '__main__':
    main()
