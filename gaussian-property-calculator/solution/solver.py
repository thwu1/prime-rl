#!/usr/bin/env python3
"""
Gaussian 16 output file property calculator.
Parses a Gaussian log file and computes molecular properties from first principles.
No cclib or external QC parsing libraries used.
"""

import json
import re
import numpy as np
import scipy.constants as spc


# ========== PARSING FUNCTIONS ==========

def read_log(filepath):
    with open(filepath) as f:
        return f.readlines()


def parse_nbasis(lines):
    for line in lines:
        m = re.search(r'(\d+)\s+basis functions', line)
        if m:
            return int(m.group(1))
    return None


def parse_n_electrons(lines):
    for line in lines:
        m = re.search(r'(\d+)\s+alpha electrons\s+(\d+)\s+beta electrons', line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def parse_initial_geometry(lines):
    """Parse first 'Input orientation' section for the initial geometry."""
    coords = []
    atomnos = []
    in_section = False
    dash_count = 0

    for line in lines:
        if 'Input orientation:' in line and not in_section:
            in_section = True
            dash_count = 0
            coords = []
            atomnos = []
            continue
        if in_section:
            if '-----' in line:
                dash_count += 1
                if dash_count == 3:
                    break
                continue
            if dash_count == 2:
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        atomnos.append(int(parts[1]))
                        coords.append([float(parts[3]), float(parts[4]), float(parts[5])])
                    except (ValueError, IndexError):
                        pass

    return np.array(coords), np.array(atomnos)


def parse_archive(lines):
    """Parse the Gaussian archive line for final geometry and properties."""
    archive = ""
    capturing = False

    for line in lines:
        if '1\\1\\GINC-' in line:
            capturing = True
        if capturing:
            content = line.rstrip('\n').rstrip('\r')
            if content.startswith(' '):
                content = content[1:]
            archive += content
            if '\\@' in line:
                break

    if not archive:
        return None, None, None

    sections = archive.split('\\\\')

    # Section 3: geometry
    geom_str = sections[3] if len(sections) > 3 else ""
    atoms_raw = geom_str.split('\\')

    elem_z = {
        'H': 1, 'He': 2, 'Li': 3, 'Be': 4, 'B': 5, 'C': 6, 'N': 7,
        'O': 8, 'F': 9, 'Ne': 10, 'S': 16, 'P': 15, 'Cl': 17,
    }

    coords = []
    atomnos = []
    for atom_str in atoms_raw:
        parts = atom_str.split(',')
        if len(parts) == 4:
            elem = parts[0].strip()
            if elem in elem_z:
                try:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    atomnos.append(elem_z[elem])
                    coords.append([x, y, z])
                except ValueError:
                    pass

    # Section 4: properties
    prop_str = sections[4] if len(sections) > 4 else ""
    hf_match = re.search(r'HF=(-?[\d.]+)', prop_str)
    hf_energy = float(hf_match.group(1)) if hf_match else None

    return np.array(coords), np.array(atomnos), hf_energy


def parse_mo_coefficients(lines, nbasis):
    """Parse MO coefficient matrix from 'Molecular Orbital Coefficients' section.

    Note: Gaussian with Population=(Regular) only prints a subset of MOs
    (occupied + a few virtual), not all nbasis MOs. The returned matrix
    will have zeros in unprinted columns.

    Returns:
        C: nbasis x n_printed MO coefficient matrix
        atom_basis_starts: dict of 0-based atom index -> 0-based first basis fn index
        n_printed: number of MO columns actually printed
    """
    C = np.zeros((nbasis, nbasis))
    atom_basis_starts = {}

    start = None
    end = None
    for i, line in enumerate(lines):
        if 'Molecular Orbital Coefficients:' in line and start is None:
            start = i + 1
        elif start is not None and 'Density Matrix:' in line:
            end = i
            break

    if start is None or end is None:
        return None, {}, 0

    current_cols = []
    max_col = 0

    for i in range(start, end):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            continue

        if re.match(r'^\d+(\s+\d+)*$', stripped):
            current_cols = [int(x) - 1 for x in stripped.split()]
            max_col = max(max_col, max(current_cols) + 1)
            continue

        if '--O' in line or '--V' in line:
            continue

        if 'Eigenvalues' in line:
            continue

        row_match = re.match(r'\s+(\d+)', line)
        if row_match and current_cols:
            row = int(row_match.group(1)) - 1

            atom_match = re.match(r'\s+\d+\s+(\d+)\s+(\w+)\s+\w+', line)
            if atom_match:
                aidx = int(atom_match.group(1)) - 1
                if aidx not in atom_basis_starts:
                    atom_basis_starts[aidx] = row

            values = re.findall(r'-?\d+\.\d+', line)
            for j, v in enumerate(values):
                if j < len(current_cols):
                    C[row, current_cols[j]] = float(v)

    return C[:, :max_col], atom_basis_starts, max_col


def parse_triangular_matrix(lines, start_header, end_header, nbasis):
    """Parse a symmetric matrix printed in lower-triangular form."""
    M = np.zeros((nbasis, nbasis))

    start = None
    end = None
    for i, line in enumerate(lines):
        if start_header in line and start is None:
            start = i + 1
        elif start is not None and end_header in line:
            end = i
            break

    if start is None:
        return None
    if end is None:
        end = len(lines)

    col_offset = 0

    for i in range(start, end):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            continue

        if re.match(r'^\d+(\s+\d+)*$', stripped):
            cols = [int(x) - 1 for x in stripped.split()]
            col_offset = cols[0]
            continue

        row_match = re.match(r'\s+(\d+)', line)
        if row_match:
            row = int(row_match.group(1)) - 1
            values = re.findall(r'-?\d+\.\d+', line)
            for j, v in enumerate(values):
                c = col_offset + j
                val = float(v)
                M[row, c] = val
                M[c, row] = val

    return M


def parse_frequencies(lines):
    """Extract harmonic vibrational frequencies (cm^-1) from the log file."""
    freqs = []
    for line in lines:
        if 'Frequencies --' in line:
            parts = line.split('--')[1].split()
            for p in parts:
                try:
                    freqs.append(float(p))
                except ValueError:
                    pass
    return np.array(freqs)


# ========== COMPUTATION FUNCTIONS ==========

def compute_nre(coords_ang, atomnos):
    """Compute nuclear repulsion energy (Hartree) from coordinates in Angstroms."""
    ang2bohr = spc.angstrom / spc.value('atomic unit of length')
    coords_bohr = coords_ang * ang2bohr

    nre = 0.0
    n = len(atomnos)
    for i in range(n):
        for j in range(i + 1, n):
            r = np.linalg.norm(coords_bohr[i] - coords_bohr[j])
            nre += atomnos[i] * atomnos[j] / r
    return nre


def compute_density_matrix(C_occ):
    """Reconstruct closed-shell density matrix: P = 2 * C_occ @ C_occ^T."""
    return 2.0 * C_occ @ C_occ.T


def compute_mulliken_charges(Q, atomnos, atom_starts, nbasis):
    """Compute Mulliken charges from the Mulliken population matrix Q.

    Q[i,j] = P[i,j] * S[i,j] (element-wise product of density and overlap).
    q_A = Z_A - sum_{i in A, j} Q[i,j]
    """
    natom = len(atomnos)
    starts = sorted(atom_starts.values())
    ends = starts[1:] + [nbasis]

    charges = []
    for a in range(natom):
        gross_pop = np.sum(Q[starts[a]:ends[a], :])
        charges.append(float(atomnos[a]) - gross_pop)

    return charges


def compute_overlap_trace(P, Q, nbasis):
    """Compute trace of overlap matrix from density and Mulliken pop matrices.

    Since Q[i,j] = P[i,j]*S[i,j], we have S[i,i] = Q[i,i]/P[i,i].
    For normalized basis functions, each S[i,i] should equal 1.
    When P[i,i] ~ 0 (unoccupied orbital due to symmetry), S[i,i] is still 1.0
    for any normalized Gaussian basis function.
    """
    trace = 0.0
    for i in range(nbasis):
        if abs(P[i, i]) > 1e-8:
            trace += Q[i, i] / P[i, i]
        else:
            # Basis function with ~zero population (symmetry-forbidden);
            # overlap self-integral is still 1.0 for normalized basis
            trace += 1.0
    return trace


def get_masses(atomnos):
    """Get most abundant isotope masses (amu)."""
    mass_table = {
        1: 1.00782503207,    # H-1
        6: 12.0,             # C-12
        7: 14.003074004,     # N-14
        8: 15.99491461956,   # O-16
    }
    return np.array([mass_table[z] for z in atomnos])


def compute_principal_moments(coords_ang, atomnos):
    """Compute principal moments of inertia in amu*bohr^2."""
    masses = get_masses(atomnos)

    com = np.sum(coords_ang * masses[:, None], axis=0) / np.sum(masses)
    rc = coords_ang - com

    ang2bohr = spc.angstrom / spc.value('atomic unit of length')
    rc_bohr = rc * ang2bohr

    I = np.zeros((3, 3))
    I[0, 0] = np.sum(masses * (rc_bohr[:, 1]**2 + rc_bohr[:, 2]**2))
    I[1, 1] = np.sum(masses * (rc_bohr[:, 0]**2 + rc_bohr[:, 2]**2))
    I[2, 2] = np.sum(masses * (rc_bohr[:, 0]**2 + rc_bohr[:, 1]**2))
    I[0, 1] = I[1, 0] = -np.sum(masses * rc_bohr[:, 0] * rc_bohr[:, 1])
    I[0, 2] = I[2, 0] = -np.sum(masses * rc_bohr[:, 0] * rc_bohr[:, 2])
    I[1, 2] = I[2, 1] = -np.sum(masses * rc_bohr[:, 1] * rc_bohr[:, 2])

    eigenvalues = np.linalg.eigvalsh(I)
    eigenvalues.sort()
    return eigenvalues.tolist()


def compute_rotational_constants(coords_ang, atomnos):
    """Compute rotational constants in GHz from coordinates in Angstroms."""
    masses = get_masses(atomnos)

    com = np.sum(coords_ang * masses[:, None], axis=0) / np.sum(masses)
    rc = coords_ang - com

    # Inertia tensor in amu*Angstrom^2
    I = np.zeros((3, 3))
    I[0, 0] = np.sum(masses * (rc[:, 1]**2 + rc[:, 2]**2))
    I[1, 1] = np.sum(masses * (rc[:, 0]**2 + rc[:, 2]**2))
    I[2, 2] = np.sum(masses * (rc[:, 0]**2 + rc[:, 1]**2))
    I[0, 1] = I[1, 0] = -np.sum(masses * rc[:, 0] * rc[:, 1])
    I[0, 2] = I[2, 0] = -np.sum(masses * rc[:, 0] * rc[:, 2])
    I[1, 2] = I[2, 1] = -np.sum(masses * rc[:, 1] * rc[:, 2])

    eigenvalues = np.linalg.eigvalsh(I)
    eigenvalues.sort()

    m_u = spc.value('unified atomic mass unit')

    rot = []
    for Iv in eigenvalues:
        I_si = Iv * m_u * (spc.angstrom)**2
        B_hz = spc.h / (8.0 * np.pi**2 * I_si)
        rot.append(B_hz / spc.giga)

    rot.sort(reverse=True)
    return rot


def compute_zpve(freqs_cm):
    """ZPVE from harmonic frequencies (cm^-1). Returns Hartree."""
    hartree_per_cm = 1.0 / 219474.6313632
    return 0.5 * np.sum(freqs_cm) * hartree_per_cm


# ========== MAIN ==========

def main():
    lines = read_log('/app/data/water.log')

    nbasis = parse_nbasis(lines)
    n_alpha, n_beta = parse_n_electrons(lines)
    n_occ = n_alpha
    print(f"nbasis={nbasis}, n_occ={n_occ}")

    # Initial geometry and NRE
    init_coords, init_atomnos = parse_initial_geometry(lines)
    nre = compute_nre(init_coords, init_atomnos)
    print(f"NRE = {nre:.10f} Hartree")

    # MO coefficients (partial: only occupied + some virtual printed)
    C, atom_basis_starts, n_printed = parse_mo_coefficients(lines, nbasis)
    print(f"MO coefs: {C.shape}, printed cols={n_printed}, atom starts={atom_basis_starts}")

    # Density matrix: reconstruct from occupied MOs
    C_occ = C[:, :n_occ]
    P_recon = compute_density_matrix(C_occ)

    # Parse printed density matrix
    P_parsed = parse_triangular_matrix(
        lines, 'Density Matrix:', 'Full Mulliken population analysis:', nbasis
    )
    max_err = float(np.max(np.abs(P_recon - P_parsed)))
    print(f"Density matrix max reconstruction error: {max_err:.6f}")

    # Parse Mulliken population matrix Q = P*S (element-wise)
    Q_parsed = parse_triangular_matrix(
        lines, 'Full Mulliken population analysis:', 'Gross orbital populations:', nbasis
    )

    # Mulliken charges from Q
    charges = compute_mulliken_charges(Q_parsed, init_atomnos, atom_basis_starts, nbasis)
    print(f"Mulliken charges: {charges}")

    # Total electrons
    total_electrons = float(np.sum(Q_parsed))
    print(f"Total electrons: {total_electrons:.4f}")

    # Overlap trace: S[i,i] = Q[i,i]/P[i,i]
    overlap_trace = compute_overlap_trace(P_parsed, Q_parsed, nbasis)
    print(f"Overlap trace: {overlap_trace:.4f}")

    # Final geometry from archive
    final_coords, final_atomnos, hf_energy = parse_archive(lines)
    print(f"HF energy: {hf_energy}")

    # Principal moments
    principal_moments = compute_principal_moments(final_coords, final_atomnos)
    print(f"Principal moments (amu*bohr^2): {principal_moments}")

    # Rotational constants
    rot_consts = compute_rotational_constants(final_coords, final_atomnos)
    print(f"Rotational constants (GHz): {rot_consts}")

    # ZPVE
    freqs = parse_frequencies(lines)
    zpve = compute_zpve(freqs)
    print(f"Frequencies (cm^-1): {freqs}")
    print(f"ZPVE: {zpve:.6f} Hartree")

    results = {
        'initial_nre_hartree': float(nre),
        'mulliken_charges': [float(c) for c in charges],
        'total_electrons': total_electrons,
        'overlap_trace': overlap_trace,
        'density_matrix_max_error': max_err,
        'final_principal_moments': principal_moments,
        'final_rotational_constants': [float(r) for r in rot_consts],
        'zpve_hartree': float(zpve),
        'final_scf_energy_hartree': float(hf_energy),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
