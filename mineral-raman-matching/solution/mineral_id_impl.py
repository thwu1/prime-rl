#!/usr/bin/env python3
"""RRUFF Mineral Identification Tool — reference implementation."""

import sys
import json
import re
import os
import argparse
import glob
import zipfile
import tempfile
import sqlite3

# ---------------------------------------------------------------------------
# Standard atomic weights (IUPAC 2021 abridged)
# ---------------------------------------------------------------------------
ATOMIC_WEIGHTS = {
    'H': 1.008, 'He': 4.003, 'Li': 6.941, 'Be': 9.012, 'B': 10.81,
    'C': 12.011, 'N': 14.007, 'O': 15.999, 'F': 18.998, 'Ne': 20.180,
    'Na': 22.990, 'Mg': 24.305, 'Al': 26.982, 'Si': 28.086, 'P': 30.974,
    'S': 32.06, 'Cl': 35.45, 'Ar': 39.948, 'K': 39.098, 'Ca': 40.078,
    'Sc': 44.956, 'Ti': 47.867, 'V': 50.942, 'Cr': 51.996, 'Mn': 54.938,
    'Fe': 55.845, 'Co': 58.933, 'Ni': 58.693, 'Cu': 63.546, 'Zn': 65.38,
    'Ga': 69.723, 'Ge': 72.630, 'As': 74.922, 'Se': 78.971, 'Br': 79.904,
    'Kr': 83.798, 'Rb': 85.468, 'Sr': 87.62, 'Y': 88.906, 'Zr': 91.224,
    'Nb': 92.906, 'Mo': 95.96, 'Ru': 101.07, 'Rh': 102.906, 'Pd': 106.42,
    'Ag': 107.868, 'Cd': 112.414, 'In': 114.818, 'Sn': 118.710,
    'Sb': 121.760, 'Te': 127.60, 'I': 126.904, 'Xe': 131.293,
    'Cs': 132.905, 'Ba': 137.327, 'La': 138.905, 'Ce': 140.116,
    'Pr': 140.908, 'Nd': 144.242, 'Sm': 150.36, 'Eu': 151.964,
    'Gd': 157.25, 'Tb': 158.925, 'Dy': 162.500, 'Ho': 164.930,
    'Er': 167.259, 'Tm': 168.934, 'Yb': 173.045, 'Lu': 174.967,
    'Hf': 178.49, 'Ta': 180.948, 'W': 183.84, 'Re': 186.207,
    'Os': 190.23, 'Ir': 192.217, 'Pt': 195.084, 'Au': 196.967,
    'Hg': 200.592, 'Tl': 204.38, 'Pb': 207.2, 'Bi': 208.980,
    'Th': 232.038, 'U': 238.029,
}

# ---------------------------------------------------------------------------
# RRUFF file parsing
# ---------------------------------------------------------------------------

def parse_rruff_file(filepath):
    """Return (metadata_dict, [(wavenumber, intensity), ...])."""
    metadata = {}
    data = []
    past_header = False
    with open(filepath) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                past_header = True
                continue
            if line.startswith('##'):
                if line.startswith('##END'):
                    break
                eq = line.find('=')
                if eq >= 0:
                    metadata[line[2:eq]] = line[eq + 1:]
            elif past_header:
                parts = line.split(',')
                if len(parts) >= 2:
                    try:
                        data.append((float(parts[0].strip()),
                                     float(parts[1].strip())))
                    except ValueError:
                        pass
    return metadata, data


def _parse_cell_params(cell_str):
    result = {}
    for key in ('a', 'b', 'c', 'alpha', 'beta', 'gamma', 'volume'):
        m = re.search(rf'{key}:\s*([\d.]+)', cell_str)
        if m:
            result[key] = float(m.group(1))
    m = re.search(r'crystal system:\s*(\w+)', cell_str)
    if m:
        result['crystal_system'] = m.group(1)
    return result

# ---------------------------------------------------------------------------
# Crystal system classification
# ---------------------------------------------------------------------------

def classify_crystal_system(a, b, c, alpha, beta, gamma,
                            angle_tol=0.5, length_tol=0.01):
    def aeq(x, y):
        return abs(x - y) <= angle_tol

    def leq(x, y):
        return abs(x - y) <= length_tol

    all_90 = aeq(alpha, 90) and aeq(beta, 90) and aeq(gamma, 90)
    ab = leq(a, b)
    bc = leq(b, c)

    if ab and bc and all_90:
        return 'cubic'
    if ab and aeq(alpha, 90) and aeq(beta, 90) and aeq(gamma, 120):
        return 'hexagonal'
    if ab and all_90:
        return 'tetragonal'
    if all_90:
        return 'orthorhombic'
    if sum([aeq(alpha, 90), aeq(beta, 90), aeq(gamma, 90)]) == 2:
        return 'monoclinic'
    return 'triclinic'

# ---------------------------------------------------------------------------
# Chemical formula parser
# ---------------------------------------------------------------------------

def _tokenize_formula(formula):
    tokens = []
    i = 0
    n = len(formula)
    while i < n:
        ch = formula[i]
        if ch == '(':
            tokens.append(('LP', None)); i += 1
        elif ch == ')':
            tokens.append(('RP', None)); i += 1
        elif ch == '_':
            end = formula.index('_', i + 1)
            s = formula[i + 1:end]
            tokens.append(('SUB', float(s.split('-')[0])))
            i = end + 1
        elif ch == '^':
            end = formula.index('^', i + 1)
            i = end + 1
        elif ch == ',':
            i += 1
            depth = 0
            while i < n:
                if formula[i] == '(':
                    depth += 1
                elif formula[i] == ')':
                    if depth == 0:
                        break
                    depth -= 1
                i += 1
        elif ch.isupper():
            elem = ch; i += 1
            if i < n and formula[i].islower():
                elem += formula[i]; i += 1
            tokens.append(('EL', elem))
        else:
            i += 1
    return tokens


def _parse_toks(tokens, pos):
    elems = {}
    while pos < len(tokens):
        tt, tv = tokens[pos]
        if tt == 'EL':
            el = tv; pos += 1
            sub = 1.0
            if pos < len(tokens) and tokens[pos][0] == 'SUB':
                sub = tokens[pos][1]; pos += 1
            elems[el] = elems.get(el, 0) + sub
        elif tt == 'LP':
            pos += 1
            grp, pos = _parse_toks(tokens, pos)
            if pos < len(tokens) and tokens[pos][0] == 'RP':
                pos += 1
            sub = 1.0
            if pos < len(tokens) and tokens[pos][0] == 'SUB':
                sub = tokens[pos][1]; pos += 1
            for e, c in grp.items():
                elems[e] = elems.get(e, 0) + c * sub
        elif tt == 'RP':
            break
        else:
            pos += 1
    return elems, pos


def parse_formula(formula_str):
    """Return (elements_dict, molecular_weight)."""
    formula_str = re.sub(r'\[box\]', '', formula_str)
    formula_str = formula_str.replace('\u25a1', '')
    tokens = _tokenize_formula(formula_str)
    elems, _ = _parse_toks(tokens, 0)
    mw = sum(ATOMIC_WEIGHTS.get(e, 0) * c for e, c in elems.items())
    return elems, mw

# ---------------------------------------------------------------------------
# Spectral library (SQLite-backed)
# ---------------------------------------------------------------------------

def _scan_directory_for_spectra(input_dir):
    """Return list of file paths to spectral files in a directory."""
    return sorted(glob.glob(os.path.join(input_dir, '*.txt')))


def build_library(source_path, output_db):
    """Build library from a directory or zip archive into SQLite database."""
    cleanup_dir = None
    if zipfile.is_zipfile(source_path) and not os.path.isdir(source_path):
        cleanup_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(source_path, 'r') as zf:
            zf.extractall(cleanup_dir)
        input_dir = cleanup_dir
    else:
        input_dir = source_path

    conn = sqlite3.connect(output_db)
    conn.execute('''CREATE TABLE IF NOT EXISTS spectra (
        name TEXT,
        rruff_id TEXT,
        wavelength INTEGER,
        wavenumbers TEXT,
        intensities TEXT
    )''')

    for fp in _scan_directory_for_spectra(input_dir):
        meta, data = parse_rruff_file(fp)
        if 'Processed' not in meta.get('FILETYPE', ''):
            continue
        if not data:
            continue
        wns = [d[0] for d in data]
        ints = [d[1] for d in data]
        mx = max(ints)
        if mx > 0:
            ints = [v / mx for v in ints]
        wl = None
        try:
            wl = int(meta.get('RAMAN WAVELENGTH', ''))
        except (ValueError, TypeError):
            pass
        conn.execute(
            'INSERT INTO spectra (name, rruff_id, wavelength, wavenumbers, intensities) VALUES (?, ?, ?, ?, ?)',
            (meta.get('NAMES', 'Unknown'), meta.get('RRUFFID', ''), wl,
             json.dumps(wns), json.dumps(ints))
        )

    conn.commit()
    conn.close()

    if cleanup_dir:
        import shutil
        shutil.rmtree(cleanup_dir, ignore_errors=True)

# ---------------------------------------------------------------------------
# Spectral identification
# ---------------------------------------------------------------------------

def identify_spectrum(query_file, library_db, top_n=5):
    import numpy as np

    q_meta, q_data = parse_rruff_file(query_file)
    if not q_data:
        return []

    q_wn = np.array([d[0] for d in q_data])
    q_int = np.array([d[1] for d in q_data], dtype=float)

    # Baseline-correct RAW spectra using iterative polynomial fitting
    if 'RAW' in q_meta.get('FILETYPE', ''):
        baseline = q_int.copy()
        for _ in range(50):
            coeffs = np.polyfit(q_wn, baseline, 4)
            baseline = np.minimum(baseline, np.polyval(coeffs, q_wn))
        coeffs = np.polyfit(q_wn, baseline, 4)
        q_int = np.maximum(q_int - np.polyval(coeffs, q_wn), 0)

    mx = np.max(q_int)
    if mx > 0:
        q_int /= mx

    q_wl = None
    try:
        q_wl = int(q_meta.get('RAMAN WAVELENGTH', ''))
    except (ValueError, TypeError):
        pass

    conn = sqlite3.connect(library_db)
    if q_wl is not None:
        cursor = conn.execute(
            'SELECT name, rruff_id, wavelength, wavenumbers, intensities FROM spectra WHERE wavelength = ?',
            (q_wl,)
        )
    else:
        cursor = conn.execute(
            'SELECT name, rruff_id, wavelength, wavenumbers, intensities FROM spectra'
        )

    results = []
    for row in cursor:
        name, rruff_id, wl, wns_json, ints_json = row
        lib_wn = np.array(json.loads(wns_json))
        lib_int = np.array(json.loads(ints_json))

        lo = max(q_wn[0], lib_wn[0])
        hi = min(q_wn[-1], lib_wn[-1])
        if lo >= hi:
            continue

        grid = np.linspace(lo, hi, 500)
        qi = np.interp(grid, q_wn, q_int)
        li = np.interp(grid, lib_wn, lib_int)

        if np.std(qi) < 1e-10 or np.std(li) < 1e-10:
            continue

        corr = float(np.corrcoef(qi, li)[0, 1])
        results.append({
            'name': name,
            'rruff_id': rruff_id,
            'score': round(corr, 6),
        })

    conn.close()
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_n]

# ---------------------------------------------------------------------------
# Cosmic ray spike detection
# ---------------------------------------------------------------------------

def detect_spikes(filepath):
    """Detect cosmic ray spikes using modified z-score with MAD."""
    import numpy as np

    meta, data = parse_rruff_file(filepath)
    if not data:
        return {"spike_count": 0, "spikes": []}

    wn = np.array([d[0] for d in data])
    intensity = np.array([d[1] for d in data], dtype=float)

    spikes = []
    half_window = 5
    threshold = 7.0  # z-score threshold

    for i in range(len(intensity)):
        lo = max(0, i - half_window)
        hi = min(len(intensity), i + half_window + 1)
        window_vals = np.concatenate([intensity[lo:i], intensity[i + 1:hi]])
        if len(window_vals) < 3:
            continue

        local_med = np.median(window_vals)
        local_mad = np.median(np.abs(window_vals - local_med))
        # MAD to std conversion factor
        sigma = local_mad * 1.4826
        if sigma < 1e-10:
            sigma = 1.0

        z = (intensity[i] - local_med) / sigma
        if z > threshold:
            # Clean by linear interpolation from nearest non-spike neighbors
            left = max(0, i - 1)
            right = min(len(intensity) - 1, i + 1)
            cleaned = (intensity[left] + intensity[right]) / 2.0
            spikes.append({
                "index": i,
                "wavenumber": round(float(wn[i]), 4),
                "original_intensity": round(float(intensity[i]), 6),
                "cleaned_intensity": round(float(cleaned), 6),
            })

    return {"spike_count": len(spikes), "spikes": spikes}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='RRUFF Mineral ID Tool')
    sub = parser.add_subparsers(dest='cmd')

    p = sub.add_parser('parse')
    p.add_argument('file')

    p = sub.add_parser('classify-crystal')
    p.add_argument('a', type=float)
    p.add_argument('b', type=float)
    p.add_argument('c', type=float)
    p.add_argument('alpha', type=float)
    p.add_argument('beta', type=float)
    p.add_argument('gamma', type=float)

    p = sub.add_parser('parse-formula')
    p.add_argument('formula')

    p = sub.add_parser('build-library')
    p.add_argument('source')
    p.add_argument('output')

    p = sub.add_parser('identify')
    p.add_argument('query')
    p.add_argument('--library', required=True)
    p.add_argument('--top', type=int, default=5)

    p = sub.add_parser('detect-spikes')
    p.add_argument('raw_file')

    args = parser.parse_args()

    if args.cmd == 'parse':
        meta, data = parse_rruff_file(args.file)
        cell = None
        if 'CELL PARAMETERS' in meta:
            cell = _parse_cell_params(meta['CELL PARAMETERS'])
        wl = None
        try:
            wl = int(meta.get('RAMAN WAVELENGTH', ''))
        except (ValueError, TypeError):
            pass
        wns = [d[0] for d in data]
        out = {
            'names': meta.get('NAMES', ''),
            'rruff_id': meta.get('RRUFFID', ''),
            'ideal_chemistry': meta.get('IDEAL CHEMISTRY', ''),
            'locality': meta.get('LOCALITY', ''),
            'cell_parameters': cell,
            'filetype': meta.get('FILETYPE', ''),
            'wavelength': wl,
            'data_points': len(data),
            'wavenumber_range': [min(wns), max(wns)] if wns else [],
        }
        print(json.dumps(out))

    elif args.cmd == 'classify-crystal':
        cs = classify_crystal_system(args.a, args.b, args.c,
                                     args.alpha, args.beta, args.gamma)
        print(json.dumps({'crystal_system': cs}))

    elif args.cmd == 'parse-formula':
        elems, mw = parse_formula(args.formula)
        print(json.dumps({
            'elements': {k: round(v, 4) for k, v in elems.items()},
            'molecular_weight': round(mw, 4),
        }))

    elif args.cmd == 'build-library':
        build_library(args.source, args.output)

    elif args.cmd == 'identify':
        matches = identify_spectrum(args.query, args.library, args.top)
        print(json.dumps(matches))

    elif args.cmd == 'detect-spikes':
        result = detect_spikes(args.raw_file)
        print(json.dumps(result))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
