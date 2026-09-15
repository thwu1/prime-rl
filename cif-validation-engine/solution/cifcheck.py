#!/usr/bin/env python3
"""CIF validation tool with dynamic rule, weight, and dictionary loading.

"""

import sys
import json
import math
import re
import os
import numpy as np


# ---------------------------------------------------------------------------
# CIF Parser
# ---------------------------------------------------------------------------

class CIFParser:
    """CIF parser supporting data blocks, scalar items, loops,
    quoted strings, semicolon-delimited text, comments, SU notation,
    and save frames (used in DDLm dictionary files)."""

    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.data_blocks = {}
        self.save_frames = {}
        self._parse()

    def _skip_ws_and_comments(self):
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in (' ', '\t', '\r', '\n'):
                self.pos += 1
            elif ch == '#':
                while self.pos < len(self.text) and self.text[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def _at_line_start(self):
        return self.pos == 0 or (self.pos > 0 and self.text[self.pos - 1] == '\n')

    def _read_token(self):
        self._skip_ws_and_comments()
        if self.pos >= len(self.text):
            return None

        # Semicolon-delimited text field (must start at beginning of line)
        if self.text[self.pos] == ';' and self._at_line_start():
            self.pos += 1
            start = self.pos
            while self.pos < len(self.text):
                if self.text[self.pos] == '\n':
                    self.pos += 1
                    if self.pos < len(self.text) and self.text[self.pos] == ';':
                        result = self.text[start:self.pos - 1]
                        self.pos += 1
                        return result
                else:
                    self.pos += 1
            return self.text[start:]

        # Single-quoted string
        if self.text[self.pos] == "'":
            self.pos += 1
            start = self.pos
            while self.pos < len(self.text):
                if self.text[self.pos] == "'" and (
                    self.pos + 1 >= len(self.text) or
                    self.text[self.pos + 1] in (' ', '\t', '\r', '\n')
                ):
                    result = self.text[start:self.pos]
                    self.pos += 1
                    return result
                self.pos += 1
            return self.text[start:]

        # Double-quoted string
        if self.text[self.pos] == '"':
            self.pos += 1
            start = self.pos
            while self.pos < len(self.text):
                if self.text[self.pos] == '"' and (
                    self.pos + 1 >= len(self.text) or
                    self.text[self.pos + 1] in (' ', '\t', '\r', '\n')
                ):
                    result = self.text[start:self.pos]
                    self.pos += 1
                    return result
                self.pos += 1
            return self.text[start:]

        # Regular unquoted token
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in (' ', '\t', '\r', '\n'):
            self.pos += 1
        return self.text[start:self.pos]

    def _parse_block_content(self, data, stop_on_save_end=False):
        """Parse tag-value pairs, loops, and save frames into data dict.
        If stop_on_save_end is True, return when a bare save_ is encountered."""
        while True:
            save_pos = self.pos
            token = self._read_token()
            if token is None:
                break

            token_lower = token.lower()

            # New data_ block — push back and let caller handle
            if token_lower.startswith('data_'):
                self.pos = save_pos
                break

            # End of save frame
            if stop_on_save_end and token_lower == 'save_':
                break

            # Start of a new save frame
            if token_lower.startswith('save_') and len(token_lower) > 5:
                frame_name = token[5:]
                frame_data = {}
                self._parse_block_content(frame_data, stop_on_save_end=True)
                self.save_frames[frame_name] = frame_data
                continue

            # Bare save_ at top level (not inside a frame) — skip
            if token_lower == 'save_':
                continue

            # Loop construct
            if token_lower == 'loop_':
                headers = []
                while True:
                    sp = self.pos
                    t = self._read_token()
                    if t is None or not t.startswith('_'):
                        self.pos = sp
                        break
                    headers.append(t.lower())

                for h in headers:
                    if h not in data:
                        data[h] = []

                n = len(headers)
                if n == 0:
                    continue

                while True:
                    sp = self.pos
                    t = self._read_token()
                    if t is None:
                        break
                    tl = t.lower()
                    if (t.startswith('_') or tl.startswith('data_') or
                            tl == 'loop_' or tl.startswith('save_')):
                        self.pos = sp
                        break
                    row = [t]
                    for _ in range(n - 1):
                        v = self._read_token()
                        if v is None:
                            break
                        row.append(v)
                    for i, h in enumerate(headers):
                        if i < len(row):
                            data[h].append(row[i])

            elif token.startswith('_'):
                value = self._read_token()
                data[token.lower()] = value

    def _parse(self):
        while True:
            token = self._read_token()
            if token is None:
                break
            token_lower = token.lower()
            if token_lower.startswith('data_'):
                block_name = token[5:]
                block_data = {}
                self._parse_block_content(block_data)
                self.data_blocks[block_name] = block_data


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def parse_cif_number(s):
    """Parse a CIF numeric value, stripping parenthesized standard uncertainty."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().strip("'").strip('"')
    if s in ('.', '?', ''):
        return None
    s = re.sub(r'\([0-9]+\)', '', s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_formula(formula_str):
    """Parse chemical formula string like 'C6 H8 O2' -> {'C': 6, 'H': 8, 'O': 2}."""
    if not formula_str:
        return {}
    formula_str = str(formula_str).strip().strip("'").strip('"')
    elements = {}
    for m in re.finditer(r'([A-Z][a-z]?)(\d*\.?\d*)', formula_str):
        elem = m.group(1)
        count_str = m.group(2)
        if elem:
            count = float(count_str) if count_str else 1.0
            elements[elem] = elements.get(elem, 0) + count
    return elements


def compute_mw(formula, atomic_weights):
    """Compute molecular weight from {element: count} dict and weight table."""
    mw = 0.0
    for elem, count in formula.items():
        if elem not in atomic_weights:
            return None
        mw += atomic_weights[elem] * count
    return mw


# ---------------------------------------------------------------------------
# Rule, weight, and dictionary loading
# ---------------------------------------------------------------------------

def load_check_rules(filepath):
    """Parse check_rules.dat -> {code: {type, severity, description}}.

    severity is either a single letter string (fixed level) or a tuple
    of three floats (C_thresh, B_thresh, A_thresh).
    """
    rules = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.split(':', 3)]
            if len(parts) < 4:
                continue
            code = parts[0]
            try:
                alert_type = int(parts[1])
            except ValueError:
                continue
            severity_raw = parts[2]
            description = parts[3]

            if '/' in severity_raw:
                try:
                    vals = tuple(float(x) for x in severity_raw.split('/'))
                    severity = vals  # (C, B, A)
                except ValueError:
                    severity = severity_raw
            else:
                severity = severity_raw.strip()

            rules[code] = {
                'type': alert_type,
                'severity': severity,
                'description': description,
            }
    return rules


def load_atomic_weights(filepath):
    """Parse element_weights.cif -> {symbol: weight}."""
    with open(filepath) as f:
        text = f.read()
    parser = CIFParser(text)
    weights = {}
    for block_name, data in parser.data_blocks.items():
        symbols = _ensure_list(data.get('_atom_type_symbol'))
        wts = _ensure_list(data.get('_atom_type_atomic_weight'))
        for sym, wt in zip(symbols, wts):
            sym_str = str(sym).strip()
            wt_val = parse_cif_number(wt)
            if sym_str and wt_val is not None:
                weights[sym_str] = wt_val
    return weights


def load_dictionary(filepath):
    """Parse CIF core dictionary subset to extract valid data item names.

    Reads save frames and collects both _definition.id and
    _alias.definition_id values as recognized CIF tag names.
    """
    with open(filepath) as f:
        text = f.read()
    parser = CIFParser(text)
    valid_tags = set()

    for frame_name, frame_data in parser.save_frames.items():
        # _definition.id (DDLm name)
        def_id = frame_data.get('_definition.id')
        if def_id:
            tag = str(def_id).strip().strip("'").strip('"').lower()
            if tag.startswith('_'):
                valid_tags.add(tag)

        # _alias.definition_id — may be scalar or list (from loop)
        alias = frame_data.get('_alias.definition_id')
        if alias is not None:
            if isinstance(alias, list):
                for a in alias:
                    tag = str(a).strip().strip("'").strip('"').lower()
                    if tag.startswith('_'):
                        valid_tags.add(tag)
            else:
                tag = str(alias).strip().strip("'").strip('"').lower()
                if tag.startswith('_'):
                    valid_tags.add(tag)

    return valid_tags


# ---------------------------------------------------------------------------
# Crystallographic computations
# ---------------------------------------------------------------------------

NA = 6.02214076e23


def compute_cell_volume(a, b, c, alpha, beta, gamma):
    """Cell volume from lengths (Ang) and angles (degrees)."""
    ar, br, gr = math.radians(alpha), math.radians(beta), math.radians(gamma)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
    val = 1.0 - ca**2 - cb**2 - cg**2 + 2.0 * ca * cb * cg
    return a * b * c * math.sqrt(abs(val))


def compute_density(z, mw, v):
    """Crystal density in g/cm3. V in Ang^3."""
    if v <= 0 or z <= 0 or mw is None:
        return None
    return z * mw / (v * NA * 1e-24)


def compute_reciprocal_lengths(a, b, c, alpha, beta, gamma):
    """Reciprocal cell vector lengths (a*, b*, c*)."""
    ar, br, gr = math.radians(alpha), math.radians(beta), math.radians(gamma)
    sa, sb, sg = math.sin(ar), math.sin(br), math.sin(gr)
    V = compute_cell_volume(a, b, c, alpha, beta, gamma)
    if V <= 0:
        return None, None, None
    a_star = b * c * sa / V
    b_star = a * c * sb / V
    c_star = a * b * sg / V
    return a_star, b_star, c_star


def compute_ueq(u11, u22, u33, u23, u13, u12, a, b, c, alpha, beta, gamma):
    """Compute Ueq per the IUCr definition (Fischer & Tillmanns 1988).

    Ueq = (1/3) * sum_ij Uij * ai* * aj* * g_ij
    where g_ij = ai . aj (metric tensor) and ai* are reciprocal lengths.
    """
    ar, br, gr = math.radians(alpha), math.radians(beta), math.radians(gamma)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)

    a_s, b_s, c_s = compute_reciprocal_lengths(a, b, c, alpha, beta, gamma)
    if a_s is None:
        return None

    g11 = a * a
    g22 = b * b
    g33 = c * c
    g12 = a * b * cg
    g13 = a * c * cb
    g23 = b * c * ca

    ueq = (1.0 / 3.0) * (
        u11 * a_s * a_s * g11 +
        u22 * b_s * b_s * g22 +
        u33 * c_s * c_s * g33 +
        2.0 * u12 * a_s * b_s * g12 +
        2.0 * u13 * a_s * c_s * g13 +
        2.0 * u23 * b_s * c_s * g23
    )
    return ueq


def get_orthogonalization_matrix(a, b, c, alpha, beta, gamma):
    """Orthogonalization matrix A (fractional -> Cartesian).
    Convention: a along x, b in xy-plane."""
    ar, br, gr = math.radians(alpha), math.radians(beta), math.radians(gamma)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
    sg = math.sin(gr)
    V = compute_cell_volume(a, b, c, alpha, beta, gamma)

    A = np.array([
        [a, b * cg, c * cb],
        [0.0, b * sg, c * (ca - cb * cg) / sg],
        [0.0, 0.0, V / (a * b * sg)],
    ])
    return A


def compute_ucart_eigenvalues(u11, u22, u33, u23, u13, u12,
                               a, b, c, alpha, beta, gamma):
    """Eigenvalues of U tensor in Cartesian frame.
    U_cart = N @ U @ N^T  where  N = A @ diag(a*, b*, c*)"""
    A = get_orthogonalization_matrix(a, b, c, alpha, beta, gamma)
    a_s, b_s, c_s = compute_reciprocal_lengths(a, b, c, alpha, beta, gamma)
    if a_s is None:
        return None

    D = np.diag([a_s, b_s, c_s])
    N = A @ D

    U = np.array([
        [u11, u12, u13],
        [u12, u22, u23],
        [u13, u23, u33],
    ])

    U_cart = N @ U @ N.T
    eigenvalues = np.linalg.eigvalsh(U_cart)
    return sorted(eigenvalues.tolist())


# ---------------------------------------------------------------------------
# Alert classification
# ---------------------------------------------------------------------------

def classify_alert(value, severity_spec):
    """Classify using either fixed level or thresholds.

    severity_spec: str (fixed level) or tuple (C, B, A thresholds).
    Returns level string or None.
    """
    if isinstance(severity_spec, str):
        return severity_spec
    c_t, b_t, a_t = severity_spec
    if value > a_t:
        return 'A'
    if value > b_t:
        return 'B'
    if value > c_t:
        return 'C'
    return None


def make_alert(code, rule, level, value, message, atom=None):
    """Build alert dict."""
    return {
        'code': code,
        'level': level,
        'type': rule['type'],
        'message': message,
        'value': value,
        'atom': atom,
    }


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def _ensure_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def validate_cif(data, rules, atomic_weights, valid_tags=None):
    """Run all enabled ALERT checks on a single CIF data block."""
    alerts = []
    computed = {}

    # ---- Extract scalar data items ----
    a = parse_cif_number(data.get('_cell_length_a'))
    b = parse_cif_number(data.get('_cell_length_b'))
    c = parse_cif_number(data.get('_cell_length_c'))
    alpha = parse_cif_number(data.get('_cell_angle_alpha'))
    beta = parse_cif_number(data.get('_cell_angle_beta'))
    gamma = parse_cif_number(data.get('_cell_angle_gamma'))
    z_val = parse_cif_number(data.get('_cell_formula_units_z'))
    v_rep = parse_cif_number(data.get('_cell_volume'))
    d_rep = parse_cif_number(data.get('_exptl_crystal_density_diffrn'))
    mw_rep = parse_cif_number(data.get('_chemical_formula_weight'))
    formula_str = data.get('_chemical_formula_sum')

    have_cell = all(x is not None for x in [a, b, c, alpha, beta, gamma])

    # ---- Compute cell volume ----
    v_calc = None
    if have_cell:
        v_calc = compute_cell_volume(a, b, c, alpha, beta, gamma)
        computed['cell_volume'] = round(v_calc, 3)

    # ---- Parse formula and compute MW ----
    formula = parse_formula(formula_str) if formula_str else {}
    formula_elements = set(formula.keys())
    mw_calc = compute_mw(formula, atomic_weights) if formula else None
    if mw_calc is not None:
        computed['formula_weight'] = round(mw_calc, 3)

    # ---- Compute density (from calculated MW & V) ----
    d_calc = None
    if z_val is not None and mw_calc is not None and v_calc is not None:
        d_calc = compute_density(z_val, mw_calc, v_calc)
        if d_calc is not None:
            computed['density'] = round(d_calc, 4)

    # ---- Extract atom-site data ----
    labels = _ensure_list(data.get('_atom_site_label'))
    types = _ensure_list(data.get('_atom_site_type_symbol'))
    ueq_reps = _ensure_list(data.get('_atom_site_u_iso_or_equiv'))
    adp_types = _ensure_list(data.get('_atom_site_adp_type'))

    # ---- Extract aniso data ----
    aniso_labels = _ensure_list(data.get('_atom_site_aniso_label'))
    aniso_u11 = _ensure_list(data.get('_atom_site_aniso_u_11'))
    aniso_u22 = _ensure_list(data.get('_atom_site_aniso_u_22'))
    aniso_u33 = _ensure_list(data.get('_atom_site_aniso_u_33'))
    aniso_u23 = _ensure_list(data.get('_atom_site_aniso_u_23'))
    aniso_u13 = _ensure_list(data.get('_atom_site_aniso_u_13'))
    aniso_u12 = _ensure_list(data.get('_atom_site_aniso_u_12'))

    # ---- Derive element info from atom_site ----
    atom_elements = set()
    for t in types:
        if t:
            m = re.match(r'([A-Z][a-z]?)', str(t))
            if m:
                atom_elements.add(m.group(1))

    # ==================================================================
    # ALERT 060: Unknown CIF data items (dictionary validation)
    # ==================================================================
    if '060' in rules and valid_tags:
        unknown_count = 0
        unknown_names = []
        all_tags = set()
        for key in data.keys():
            if key.startswith('_'):
                all_tags.add(key)
        for tag in sorted(all_tags):
            if tag not in valid_tags:
                unknown_count += 1
                unknown_names.append(tag)
        if unknown_count > 0:
            rule = rules['060']
            level = classify_alert(1, rule['severity'])
            alerts.append(make_alert(
                '060', rule, level, unknown_count,
                f'Unknown CIF Data Item(s): {", ".join(unknown_names)}'))

    # ==================================================================
    # ALERT 040: Carbon present but no H in atom_site
    # ==================================================================
    if '040' in rules:
        has_carbon = 'C' in atom_elements or 'C' in formula_elements
        has_hydrogen = 'H' in atom_elements

        if has_carbon and not has_hydrogen and len(labels) > 0:
            rule = rules['040']
            level = classify_alert(1, rule['severity'])
            alerts.append(make_alert(
                '040', rule, level, 1,
                'No H-atoms in this Carbon Containing Compound'))

    # ==================================================================
    # ALERT 041: Element types in atom_site != formula
    # ==================================================================
    if '041' in rules:
        if formula_elements and atom_elements:
            if formula_elements != atom_elements:
                rule = rules['041']
                level = classify_alert(1, rule['severity'])
                alerts.append(make_alert(
                    '041', rule, level, 1,
                    'Calc. and Reported SumFormula Strings Differ'))

    # ==================================================================
    # ALERT 043: MW percentage difference
    # ==================================================================
    if '043' in rules:
        if mw_calc is not None and mw_rep is not None and mw_rep > 0:
            pct = abs(mw_calc - mw_rep) / mw_rep * 100.0
            rule = rules['043']
            level = classify_alert(pct, rule['severity'])
            if level:
                alerts.append(make_alert(
                    '043', rule, level, round(pct, 4),
                    f'Calculated and Reported Mol. Weight Differ by {pct:.2f}%'))

    # ==================================================================
    # ALERT 044: Density diff (calc MW & V vs reported density)
    # ==================================================================
    if '044' in rules:
        if d_calc is not None and d_rep is not None and d_rep > 0:
            pct = abs(d_calc - d_rep) / d_rep * 100.0
            rule = rules['044']
            level = classify_alert(pct, rule['severity'])
            if level:
                alerts.append(make_alert(
                    '044', rule, level, round(pct, 4),
                    f'Calculated and Reported Density Dx Differ by {pct:.2f}%'))

    # ==================================================================
    # ALERT 046: D from reported Z, MW_rep, V_rep vs D_rep
    # ==================================================================
    if '046' in rules:
        if (z_val is not None and mw_rep is not None and v_rep is not None
                and d_rep is not None and d_rep > 0 and v_rep > 0):
            d_zmw = compute_density(z_val, mw_rep, v_rep)
            if d_zmw is not None:
                pct = abs(d_zmw - d_rep) / d_rep * 100.0
                rule = rules['046']
                level = classify_alert(pct, rule['severity'])
                if level:
                    alerts.append(make_alert(
                        '046', rule, level, round(pct, 4),
                        f'Reported Z, MW and D(calc) are Inconsistent by {pct:.2f}%'))

    # ==================================================================
    # ALERT 049: Computed density < 1.0
    # ==================================================================
    if '049' in rules:
        if d_calc is not None and d_calc < 1.0:
            rule = rules['049']
            level = classify_alert(1, rule['severity'])
            alerts.append(make_alert(
                '049', rule, level, round(d_calc, 4),
                f'Calculated Density Less Than 1.0 gcm-3: {d_calc:.4f}'))

    # ==================================================================
    # ALERT 201: Isotropic non-H atoms
    # ==================================================================
    if '201' in rules:
        aniso_set = set(str(lbl) for lbl in aniso_labels)
        iso_nonH_count = 0
        for i, label in enumerate(labels):
            label_str = str(label)
            type_sym = str(types[i]) if i < len(types) else ''
            adp = str(adp_types[i]).strip() if i < len(adp_types) else ''

            m = re.match(r'([A-Z][a-z]?)', type_sym)
            elem_name = m.group(1) if m else ''

            if elem_name and elem_name != 'H':
                if adp.lower() == 'uiso' or label_str not in aniso_set:
                    iso_nonH_count += 1

        if iso_nonH_count > 0:
            rule = rules['201']
            level = classify_alert(iso_nonH_count, rule['severity'])
            if level:
                alerts.append(make_alert(
                    '201', rule, level, iso_nonH_count,
                    f'Isotropic non-H Atoms in Main Residue(s): {iso_nonH_count}'))

    # ==================================================================
    # Per-atom ADP checks (211, 213, 224)
    # ==================================================================
    ueq_computed = {}

    label_to_idx = {}
    for i, lbl in enumerate(labels):
        label_to_idx[str(lbl)] = i

    if have_cell and aniso_labels:
        for i, label in enumerate(aniso_labels):
            label_str = str(label)

            u11 = parse_cif_number(aniso_u11[i]) if i < len(aniso_u11) else None
            u22 = parse_cif_number(aniso_u22[i]) if i < len(aniso_u22) else None
            u33 = parse_cif_number(aniso_u33[i]) if i < len(aniso_u33) else None
            u23 = parse_cif_number(aniso_u23[i]) if i < len(aniso_u23) else None
            u13 = parse_cif_number(aniso_u13[i]) if i < len(aniso_u13) else None
            u12 = parse_cif_number(aniso_u12[i]) if i < len(aniso_u12) else None

            if any(x is None for x in [u11, u22, u33, u23, u13, u12]):
                continue

            # -- Compute Ueq --
            ueq_calc = compute_ueq(u11, u22, u33, u23, u13, u12,
                                   a, b, c, alpha, beta, gamma)
            if ueq_calc is not None:
                ueq_computed[label_str] = round(ueq_calc, 5)

            # -- ALERT 224: Ueq mismatch --
            if '224' in rules:
                idx = label_to_idx.get(label_str)
                if idx is not None and idx < len(ueq_reps) and ueq_calc is not None:
                    ueq_rep_val = parse_cif_number(ueq_reps[idx])
                    if ueq_rep_val is not None:
                        diff = abs(ueq_calc - ueq_rep_val)
                        rule = rules['224']
                        level = classify_alert(diff, rule['severity'])
                        if level:
                            alerts.append(make_alert(
                                '224', rule, level, round(diff, 5),
                                f'Ueq(Rep) and Ueq(Calc) Differ by '
                                f'{diff:.4f} Ang**2 for {label_str}',
                                atom=label_str))

            # -- Compute eigenvalues --
            try:
                eigenvalues = compute_ucart_eigenvalues(
                    u11, u22, u33, u23, u13, u12,
                    a, b, c, alpha, beta, gamma)
            except Exception:
                continue

            if eigenvalues is None:
                continue

            # -- ALERT 211: NPD check --
            if eigenvalues[0] < -1e-10:
                if '211' in rules:
                    rule = rules['211']
                    level = classify_alert(1, rule['severity'])
                    alerts.append(make_alert(
                        '211', rule, level, round(eigenvalues[0], 6),
                        f'Non-Positive Definite ADP for {label_str}',
                        atom=label_str))
            else:
                # -- ALERT 213: ADP ratio (skip for NPD) --
                if '213' in rules:
                    umin = eigenvalues[0]
                    umax = eigenvalues[2]
                    if umin > 1e-10:
                        ratio = math.sqrt(umax / umin)
                        rule = rules['213']
                        level = classify_alert(ratio, rule['severity'])
                        if level:
                            alerts.append(make_alert(
                                '213', rule, level, round(ratio, 4),
                                f'Atom {label_str} has ADP max/min '
                                f'Ratio {ratio:.3f}',
                                atom=label_str))

    if ueq_computed:
        computed['ueq'] = ueq_computed

    return alerts, computed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 cifcheck.py <cif_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]

    # Determine base directory for data files
    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_path = os.path.join(script_dir, 'check_rules.dat')
    weights_path = os.path.join(script_dir, 'element_weights.cif')
    dict_path = os.path.join(script_dir, 'cif_core_subset.dic')

    # Load rules, weights, and dictionary dynamically
    rules = load_check_rules(rules_path)
    atomic_weights = load_atomic_weights(weights_path)
    valid_tags = load_dictionary(dict_path) if os.path.exists(dict_path) else set()

    with open(filepath, 'r') as f:
        text = f.read()

    parser = CIFParser(text)

    results = []
    for block_name, data in parser.data_blocks.items():
        block_alerts, block_computed = validate_cif(
            data, rules, atomic_weights, valid_tags)
        results.append({
            'data_block': block_name,
            'alerts': block_alerts,
            'computed': block_computed,
        })

    if len(results) == 1:
        output = results[0]
    elif len(results) == 0:
        output = {'data_block': '', 'alerts': [], 'computed': {}}
    else:
        output = results

    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
