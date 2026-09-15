#!/usr/bin/env python3
"""Powder X-ray Diffraction Pattern Simulator and Phase Identifier.


Parses CIF files, applies symmetry operations, computes simulated
powder XRD patterns from first principles using atomic scattering
factors, and performs phase identification against a library of CIFs.
"""

import sys
import os
import json
import argparse
import re
import math
import urllib.request
import urllib.error
import numpy as np

# ============================================================
# Cromer-Mann 4-Gaussian atomic scattering factor coefficients
# f(s) = sum_i(a_i * exp(-b_i * s^2)) + c,  s = sin(theta)/lambda
# ============================================================
CROMER_MANN = {
    'H':  ([0.489918, 0.262003, 0.196767, 0.049879],
           [20.6593, 7.74039, 49.5519, 2.20159], 0.001305),
    'He': ([0.8734, 0.6309, 0.3112, 0.1780],
           [9.1037, 3.3568, 22.9276, 0.9821], 0.0064),
    'Li': ([1.1282, 0.7508, 0.6175, 0.4653],
           [3.9546, 1.0524, 85.3905, 168.261], 0.0377),
    'Be': ([1.5919, 1.1278, 0.5391, 0.7029],
           [43.6427, 1.8623, 103.483, 0.5420], 0.0385),
    'B':  ([2.0545, 1.3326, 1.0979, 0.7068],
           [23.2185, 1.0210, 60.3498, 0.1403], -0.1932),
    'C':  ([2.3100, 1.0200, 1.5886, 0.8650],
           [20.8439, 10.2075, 0.5687, 51.6512], 0.2156),
    'N':  ([12.2126, 3.1322, 2.0125, 1.1663],
           [0.0057, 9.8933, 28.9975, 0.5826], -11.529),
    'O':  ([3.0485, 2.2868, 1.5463, 0.8670],
           [13.2771, 5.7011, 0.3239, 32.9089], 0.2508),
    'F':  ([3.5392, 2.6412, 1.5170, 1.0243],
           [10.2825, 4.2944, 0.2615, 26.1476], 0.2776),
    'Ne': ([3.9553, 3.1125, 1.4546, 1.1251],
           [8.4042, 3.4262, 0.2306, 21.7184], 0.3515),
    'Na': ([4.7626, 3.1736, 1.2674, 1.1128],
           [3.2850, 8.8422, 0.3136, 129.424], 0.6760),
    'Mg': ([5.4204, 2.1735, 1.2269, 2.3073],
           [2.8275, 79.2611, 0.3808, 7.1937], 0.8584),
    'Al': ([6.4202, 1.9002, 1.5936, 1.9646],
           [3.0387, 0.7426, 31.5472, 85.0886], 1.1151),
    'Si': ([6.2915, 3.0353, 1.9891, 1.5410],
           [2.4386, 32.3337, 0.6785, 81.6937], 1.1407),
    'P':  ([6.4345, 4.1791, 1.7800, 1.4908],
           [1.9067, 27.1570, 0.5260, 68.1645], 1.1149),
    'S':  ([6.9053, 5.2034, 1.4379, 1.5863],
           [1.4679, 22.2151, 0.2536, 56.1720], 0.8669),
    'Cl': ([11.4604, 7.1964, 6.2556, 1.6455],
           [0.0104, 1.1662, 18.5194, 47.7784], -9.5574),
    'Ar': ([7.4845, 6.7723, 0.6539, 1.6442],
           [0.9072, 14.8407, 43.8983, 33.3929], 1.4445),
    'K':  ([8.2186, 7.4398, 1.0519, 0.8659],
           [12.7949, 0.7748, 213.187, 41.6841], 1.4228),
    'Ca': ([8.6266, 7.3873, 1.5899, 1.0211],
           [10.4421, 0.6599, 85.7484, 178.437], 1.3751),
    'Sc': ([9.1890, 7.3679, 1.6409, 1.4680],
           [9.0213, 0.5729, 136.108, 51.3531], 1.3329),
    'Ti': ([9.7595, 7.3558, 1.6991, 1.9021],
           [7.8508, 0.5000, 35.6338, 116.105], 1.2807),
    'V':  ([10.2971, 7.3511, 2.0703, 2.0571],
           [6.8657, 0.4385, 26.8938, 102.478], 1.2199),
    'Cr': ([10.6406, 7.3537, 3.3240, 1.4922],
           [6.1038, 0.3920, 20.2626, 98.7399], 1.1832),
    'Mn': ([11.2819, 7.3573, 3.0193, 2.2441],
           [5.3409, 0.3432, 17.8674, 83.7543], 1.0896),
    'Fe': ([11.7695, 7.3573, 3.5222, 2.3045],
           [4.7611, 0.3072, 15.3535, 76.8805], 1.0369),
    'Co': ([12.2841, 7.3409, 4.0034, 2.3488],
           [4.2791, 0.2784, 13.5359, 71.1692], 1.0118),
    'Ni': ([12.8376, 7.2920, 4.4438, 2.3800],
           [3.8785, 0.2565, 12.1763, 66.3421], 1.0341),
    'Cu': ([13.3380, 7.1676, 5.6158, 1.6735],
           [3.5828, 0.2470, 11.3966, 64.8126], 1.1910),
    'Zn': ([14.0743, 7.0318, 5.1652, 2.4100],
           [3.2655, 0.2333, 10.3163, 58.7097], 1.3041),
    'Ga': ([15.2354, 6.7006, 4.3591, 2.9623],
           [3.0669, 0.2412, 10.7805, 61.4135], 1.7189),
    'Ge': ([16.0816, 6.3747, 3.7068, 3.6830],
           [2.8509, 0.2516, 11.4468, 54.7625], 2.1313),
    'Sr': ([17.5663, 9.8184, 5.4220, 2.6694],
           [1.5564, 14.0988, 0.1664, 132.376], 2.5064),
    'Y':  ([17.7760, 10.2946, 5.7269, 3.2656],
           [1.4029, 12.8006, 0.1255, 104.354], 1.9124),
    'Zr': ([17.8765, 10.9480, 5.4173, 3.6572],
           [1.2764, 11.9160, 0.1176, 87.6627], 2.0692),
    'Ba': ([20.3361, 19.2970, 10.8882, 2.6959],
           [3.2160, 0.2756, 20.2073, 167.202], 2.7731),
}


# ============================================================
# CIF Parser
# ============================================================

def parse_cif_value(val_str):
    """Parse a CIF numeric value, stripping standard uncertainties."""
    val_str = val_str.strip().strip("'\"")
    val_str = re.sub(r'\(\d+\)', '', val_str)
    try:
        return float(val_str)
    except ValueError:
        return val_str


def tokenize_cif_values(line):
    """Tokenize a CIF value line respecting single-quoted strings."""
    tokens = []
    i = 0
    while i < len(line):
        if line[i] in (' ', '\t'):
            i += 1
            continue
        if line[i] == "'":
            end = line.find("'", i + 1)
            if end == -1:
                end = len(line)
            tokens.append(line[i:end + 1])
            i = end + 1
        elif line[i] == '"':
            end = line.find('"', i + 1)
            if end == -1:
                end = len(line)
            tokens.append(line[i:end + 1])
            i = end + 1
        else:
            end = i
            while end < len(line) and line[end] not in (' ', '\t'):
                end += 1
            tokens.append(line[i:end])
            i = end
    return tokens


def parse_cif(filepath):
    """Parse a CIF file and return structured crystal data."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    data = {
        'cell': {},
        'space_group': '',
        'crystal_system': '',
        'symmetry_ops': [],
        'atoms': []
    }

    cell_tags = {
        '_cell_length_a': 'a', '_cell_length_b': 'b', '_cell_length_c': 'c',
        '_cell_angle_alpha': 'alpha', '_cell_angle_beta': 'beta',
        '_cell_angle_gamma': 'gamma',
    }

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith('#'):
            i += 1
            continue

        # Scalar tag-value pairs
        for tag, param in cell_tags.items():
            if line.lower().startswith(tag.lower()):
                parts = line.split()
                if len(parts) >= 2:
                    data['cell'][param] = parse_cif_value(parts[-1])
                break

        if line.startswith('_symmetry_space_group_name_H-M') or \
           line.startswith('_space_group_name_H-M'):
            match = re.search(r"['\"](.+?)['\"]", line)
            if match:
                data['space_group'] = match.group(1)
            else:
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    data['space_group'] = parts[1].strip()

        if line.startswith('_symmetry_cell_setting') or \
           line.startswith('_space_group_crystal_system'):
            parts = line.split()
            if len(parts) >= 2:
                data['crystal_system'] = parts[-1].strip()

        # Loop constructs
        if line.lower() == 'loop_':
            i += 1
            loop_tags = []
            while i < len(lines) and lines[i].strip().startswith('_'):
                loop_tags.append(lines[i].strip())
                i += 1

            loop_rows = []
            while i < len(lines):
                vline = lines[i].strip()
                if not vline or vline.startswith('_') or \
                   vline.lower() == 'loop_' or vline.startswith('data_'):
                    break
                if vline.startswith('#'):
                    i += 1
                    continue
                loop_rows.append(vline)
                i += 1

            sym_tag = None
            for t in ['_symmetry_equiv_pos_as_xyz',
                       '_space_group_symop_operation_xyz']:
                if t in loop_tags:
                    sym_tag = t
                    break

            if sym_tag is not None:
                sym_idx = loop_tags.index(sym_tag)
                for row in loop_rows:
                    match = re.search(r"'([^']+)'", row)
                    if match:
                        data['symmetry_ops'].append(match.group(1))
                    else:
                        tokens = tokenize_cif_values(row)
                        if sym_idx < len(tokens):
                            data['symmetry_ops'].append(
                                tokens[sym_idx].strip("'\""))

            atom_tags = [t for t in loop_tags if '_atom_site' in t]
            if atom_tags:
                tag_idx = {t: j for j, t in enumerate(loop_tags)}
                for row in loop_rows:
                    tokens = tokenize_cif_values(row)
                    if len(tokens) < len(loop_tags):
                        continue
                    atom = {}
                    if '_atom_site_type_symbol' in tag_idx:
                        raw = tokens[tag_idx['_atom_site_type_symbol']].strip("'\"")
                        atom['element'] = re.match(r'([A-Z][a-z]?)', raw).group(1)
                    elif '_atom_site_label' in tag_idx:
                        raw = tokens[tag_idx['_atom_site_label']].strip("'\"")
                        atom['element'] = re.match(r'([A-Z][a-z]?)', raw).group(1)
                    else:
                        continue
                    if '_atom_site_label' in tag_idx:
                        atom['label'] = tokens[tag_idx['_atom_site_label']]
                    for coord, key in [('_atom_site_fract_x', 'x'),
                                        ('_atom_site_fract_y', 'y'),
                                        ('_atom_site_fract_z', 'z')]:
                        if coord in tag_idx:
                            atom[key] = float(parse_cif_value(
                                tokens[tag_idx[coord]]))
                    if '_atom_site_occupancy' in tag_idx:
                        atom['occupancy'] = float(parse_cif_value(
                            tokens[tag_idx['_atom_site_occupancy']]))
                    else:
                        atom['occupancy'] = 1.0
                    atom['U_iso'] = 0.0
                    if '_atom_site_U_iso_or_equiv' in tag_idx:
                        val = parse_cif_value(
                            tokens[tag_idx['_atom_site_U_iso_or_equiv']])
                        if isinstance(val, (int, float)):
                            atom['U_iso'] = float(val)
                    elif '_atom_site_B_iso_or_equiv' in tag_idx:
                        val = parse_cif_value(
                            tokens[tag_idx['_atom_site_B_iso_or_equiv']])
                        if isinstance(val, (int, float)):
                            atom['U_iso'] = float(val) / (8.0 * math.pi ** 2)
                    data['atoms'].append(atom)
            continue

        i += 1

    return data


# ============================================================
# Symmetry Operations
# ============================================================

def _parse_sym_component(s):
    """Parse one component like '-x+y+2/3' into (cx, cy, cz, t)."""
    s = s.strip().replace(' ', '')
    cx, cy, cz, t = 0.0, 0.0, 0.0, 0.0
    if not s:
        return cx, cy, cz, t
    if s[0] not in '+-':
        s = '+' + s
    tokens = re.findall(r'[+-][^+-]+', s)
    for tok in tokens:
        tok = tok.strip()
        if 'x' in tok:
            c = tok.replace('x', '').strip()
            cx = 1.0 if c in ('+', '') else (-1.0 if c == '-' else float(c))
        elif 'y' in tok:
            c = tok.replace('y', '').strip()
            cy = 1.0 if c in ('+', '') else (-1.0 if c == '-' else float(c))
        elif 'z' in tok:
            c = tok.replace('z', '').strip()
            cz = 1.0 if c in ('+', '') else (-1.0 if c == '-' else float(c))
        else:
            if '/' in tok:
                num, den = tok.split('/')
                t += float(num) / float(den)
            else:
                try:
                    t += float(tok)
                except ValueError:
                    pass
    return cx, cy, cz, t


def parse_symmetry_operation(op_str):
    """Parse 'x, y, z' style string into 3x3 rotation + 3-vector translation."""
    parts = op_str.split(',')
    R = np.zeros((3, 3))
    tvec = np.zeros(3)
    for i, part in enumerate(parts):
        cx, cy, cz, ti = _parse_sym_component(part)
        R[i] = [cx, cy, cz]
        tvec[i] = ti
    return R, tvec


def expand_symmetry(atoms, sym_ops, tol=0.01):
    """Apply symmetry operations to expand asymmetric unit to full unit cell."""
    expanded = []
    for atom in atoms:
        pos = np.array([atom['x'], atom['y'], atom['z']])
        unique_positions = []
        for op_str in sym_ops:
            R, tvec = parse_symmetry_operation(op_str)
            new_pos = R @ pos + tvec
            new_pos = new_pos % 1.0
            new_pos[np.abs(new_pos - 1.0) < 1e-10] = 0.0
            new_pos[np.abs(new_pos) < 1e-10] = 0.0
            is_dup = False
            for existing in unique_positions:
                diff = np.abs(new_pos - existing)
                diff = np.minimum(diff, 1.0 - diff)
                if np.all(diff < tol):
                    is_dup = True
                    break
            if not is_dup:
                unique_positions.append(new_pos)
        for upos in unique_positions:
            expanded.append({
                'element': atom['element'],
                'x': float(upos[0]),
                'y': float(upos[1]),
                'z': float(upos[2]),
                'occupancy': atom['occupancy'],
                'U_iso': atom.get('U_iso', 0.0),
            })
    return expanded


# ============================================================
# Crystallographic Computations
# ============================================================

def metric_tensor(a, b, c, alpha_deg, beta_deg, gamma_deg):
    """Compute direct metric tensor G, its inverse G*, and cell volume V."""
    ar = math.radians(alpha_deg)
    br = math.radians(beta_deg)
    gr = math.radians(gamma_deg)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
    G = np.array([
        [a * a,      a * b * cg, a * c * cb],
        [a * b * cg, b * b,      b * c * ca],
        [a * c * cb, b * c * ca, c * c     ],
    ])
    V = a * b * c * math.sqrt(
        1 - ca ** 2 - cb ** 2 - cg ** 2 + 2 * ca * cb * cg)
    G_star = np.linalg.inv(G)
    return G, G_star, V


def d_spacing_from_hkl(h, k, l, G_star):
    """Compute d-spacing using reciprocal metric tensor."""
    hkl = np.array([h, k, l], dtype=float)
    val = hkl @ G_star @ hkl
    if val <= 0:
        return float('inf')
    return 1.0 / math.sqrt(val)


def atomic_scatt_factor(element, s):
    """Compute f(s) for element, s = sin(theta)/lambda."""
    el = element.strip()
    if el not in CROMER_MANN:
        el = el[:2] if len(el) >= 2 else el
    if el not in CROMER_MANN:
        el = el[0]
    if el not in CROMER_MANN:
        a_arr, b_arr, c_val = CROMER_MANN['C']
    else:
        a_arr, b_arr, c_val = CROMER_MANN[el]
    s2 = s * s
    f = c_val
    for ai, bi in zip(a_arr, b_arr):
        f += ai * math.exp(-bi * s2)
    return f


def structure_factor(h, k, l, atoms, s):
    """Compute complex structure factor F(hkl)."""
    F_re = 0.0
    F_im = 0.0
    two_pi = 2.0 * math.pi
    for atom in atoms:
        f_j = atomic_scatt_factor(atom['element'], s)
        occ = atom['occupancy']
        u_iso = atom.get('U_iso', 0.0)
        dw = math.exp(-8.0 * math.pi ** 2 * u_iso * s * s) if u_iso > 0 else 1.0
        phase = two_pi * (h * atom['x'] + k * atom['y'] + l * atom['z'])
        coeff = f_j * occ * dw
        F_re += coeff * math.cos(phase)
        F_im += coeff * math.sin(phase)
    return F_re, F_im


def lorentz_polarization(two_theta_rad):
    """LP = (1 + cos^2(2theta)) / (sin^2(theta) * cos(theta))."""
    theta = two_theta_rad / 2.0
    st = math.sin(theta)
    ct = math.cos(theta)
    c2t = math.cos(two_theta_rad)
    denom = st * st * ct
    if abs(denom) < 1e-15:
        return 0.0
    return (1.0 + c2t * c2t) / denom


# ============================================================
# Powder XRD Pattern Simulation
# ============================================================

def _merge_key(d_val, groups, tol=1e-4):
    """Find existing group key within tolerance, or return d_val as new key."""
    for gk in groups:
        if abs(gk - d_val) < tol:
            return gk
    return d_val


def simulate(cif_data, wavelength, two_theta_max):
    """Simulate a powder XRD pattern and return a result dict."""
    cell = cif_data['cell']
    a, b, c = cell['a'], cell['b'], cell['c']
    alpha, beta, gamma = cell['alpha'], cell['beta'], cell['gamma']
    _, G_star, V = metric_tensor(a, b, c, alpha, beta, gamma)

    all_atoms = expand_symmetry(cif_data['atoms'], cif_data['symmetry_ops'])

    two_theta_max_rad = math.radians(two_theta_max)
    sin_theta_max = math.sin(two_theta_max_rad / 2.0)
    d_min = wavelength / (2.0 * sin_theta_max) if sin_theta_max > 1e-10 else 0.5

    h_max = int(math.ceil(a / d_min)) + 1
    k_max = int(math.ceil(b / d_min)) + 1
    l_max = int(math.ceil(c / d_min)) + 1

    groups = {}  # d_key -> {'d': float, 'two_theta': float, 'F_sq_sum': float,
                 #           'mult': int, 'rep_hkl': (h,k,l)}

    for h in range(-h_max, h_max + 1):
        for k in range(-k_max, k_max + 1):
            for l in range(-l_max, l_max + 1):
                if h == 0 and k == 0 and l == 0:
                    continue
                d = d_spacing_from_hkl(h, k, l, G_star)
                if d < d_min or d > 1e6:
                    continue
                sin_th = wavelength / (2.0 * d)
                if sin_th > 1.0 or sin_th <= 0:
                    continue
                two_th = 2.0 * math.asin(sin_th)
                if math.degrees(two_th) > two_theta_max:
                    continue

                s = sin_th / wavelength
                F_re, F_im = structure_factor(h, k, l, all_atoms, s)
                F_sq = F_re * F_re + F_im * F_im
                if F_sq < 1e-6:
                    continue

                dk = _merge_key(round(d, 6), groups)
                if dk not in groups:
                    groups[dk] = {
                        'd': d,
                        'two_theta': math.degrees(two_th),
                        'F_sq_sum': F_sq,
                        'mult': 1,
                        'rep_hkl': (abs(h), abs(k), abs(l)),
                    }
                else:
                    groups[dk]['F_sq_sum'] += F_sq
                    groups[dk]['mult'] += 1
                    cand = tuple(sorted((abs(h), abs(k), abs(l)), reverse=True))
                    cur = groups[dk]['rep_hkl']
                    if cand < tuple(sorted(cur, reverse=True)):
                        groups[dk]['rep_hkl'] = cand

    peaks = []
    for gk, gv in groups.items():
        two_th_rad = math.radians(gv['two_theta'])
        lp = lorentz_polarization(two_th_rad)
        intensity = gv['F_sq_sum'] * lp
        if intensity < 1e-10:
            continue
        hkl_sorted = sorted(gv['rep_hkl'], reverse=True)
        peaks.append({
            'hkl': list(hkl_sorted),
            'd_spacing': round(gv['d'], 5),
            'two_theta': round(gv['two_theta'], 4),
            'intensity': intensity,
            'multiplicity': gv['mult'],
        })

    peaks.sort(key=lambda p: p['two_theta'])

    if peaks:
        max_int = max(p['intensity'] for p in peaks)
        if max_int > 0:
            for p in peaks:
                p['intensity'] = round(100.0 * p['intensity'] / max_int, 4)

    peaks = [p for p in peaks if p['intensity'] >= 0.1]

    return {
        'cell': {
            'a': cell['a'], 'b': cell['b'], 'c': cell['c'],
            'alpha': cell['alpha'], 'beta': cell['beta'], 'gamma': cell['gamma'],
        },
        'volume': round(V, 2),
        'space_group': cif_data['space_group'],
        'num_atoms_asymmetric': len(cif_data['atoms']),
        'num_atoms_unit_cell': len(all_atoms),
        'peaks': peaks,
    }


# ============================================================
# Phase Identification
# ============================================================

def figure_of_merit(observed_peaks, simulated_peaks, tol=1.0):
    """Intensity-weighted peak-position matching score in [0, 1]."""
    if not observed_peaks or not simulated_peaks:
        return 0.0
    sim_2th = np.array([p['two_theta'] for p in simulated_peaks])
    total_weight = 0.0
    total_score = 0.0
    for obs in observed_peaks:
        obs_2th = obs['two_theta']
        obs_int = obs.get('intensity', 1.0)
        diffs = np.abs(sim_2th - obs_2th)
        min_diff = float(np.min(diffs))
        if min_diff < tol:
            score = 1.0 - min_diff / tol
        else:
            score = 0.0
        total_score += obs_int * score
        total_weight += obs_int
    return total_score / total_weight if total_weight > 0 else 0.0


def identify(observed_path, cif_dir, wavelength):
    """Identify the best-matching CIF file for observed peaks."""
    with open(observed_path) as f:
        obs_data = json.load(f)
    obs_peaks = obs_data.get('peaks', [])

    cif_files = sorted(
        fn for fn in os.listdir(cif_dir)
        if fn.lower().endswith('.cif'))

    rankings = []
    for fn in cif_files:
        path = os.path.join(cif_dir, fn)
        try:
            cif_data = parse_cif(path)
            sim_result = simulate(cif_data, wavelength, 120.0)
            score = figure_of_merit(obs_peaks, sim_result['peaks'])
        except Exception:
            score = 0.0
        rankings.append({'file': fn, 'score': round(score, 6)})

    rankings.sort(key=lambda r: r['score'], reverse=True)
    best = rankings[0]['file'] if rankings else ''

    return {
        'best_match': best,
        'rankings': rankings,
    }


# ============================================================
# COD Fetch
# ============================================================

def fetch_cif(cod_id, output_path):
    """Download a CIF file from the Crystallography Open Database."""
    url = f"https://www.crystallography.net/cod/{cod_id}.cif"
    try:
        urllib.request.urlretrieve(url, output_path)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"Error fetching COD entry {cod_id}: {e}", file=sys.stderr)
        sys.exit(1)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Powder XRD simulator and phase identifier')
    sub = parser.add_subparsers(dest='command')

    sim_p = sub.add_parser('simulate')
    sim_p.add_argument('cif_file')
    sim_p.add_argument('--wavelength', type=float, required=True)
    sim_p.add_argument('--two-theta-max', type=float, required=True)
    sim_p.add_argument('--output', required=True)

    id_p = sub.add_parser('identify')
    id_p.add_argument('observed_json')
    id_p.add_argument('cif_dir')
    id_p.add_argument('--wavelength', type=float, required=True)
    id_p.add_argument('--output', required=True)

    fetch_p = sub.add_parser('fetch')
    fetch_p.add_argument('cod_id')
    fetch_p.add_argument('--output', required=True)

    args = parser.parse_args()

    if args.command == 'simulate':
        cif_data = parse_cif(args.cif_file)
        result = simulate(cif_data, args.wavelength, args.two_theta_max)
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)

    elif args.command == 'identify':
        result = identify(args.observed_json, args.cif_dir, args.wavelength)
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)

    elif args.command == 'fetch':
        fetch_cif(args.cod_id, args.output)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
