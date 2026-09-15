"""
Test suite for the CAPRI docking quality scorer.

Generates PDB test data with known geometry, computes expected metrics
using a Python reference implementation, and compares against C++ output.

"""

import os
import subprocess
import tempfile
import math
import pytest
import numpy as np

BINARY = "/app/capri_scorer"
CUTOFF = 5.0
TOLERANCE = 0.02  # tolerance for floating-point comparison


# ============================================================
# PDB generation helpers
# ============================================================

def pdb_line(serial, name, resname, chain, resseq, x, y, z, element):
    """Format a single PDB ATOM record."""
    if len(name) < 4:
        if name[0].isdigit():
            nf = f"{name:<4s}"
        else:
            nf = f" {name:<3s}"
    else:
        nf = name[:4]
    return (
        f"ATOM  {serial:5d} {nf} {resname:>3s} {chain}{resseq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2s}"
    )


def make_chain(chain_id, residues, res_start=1, resname="ALA",
               include_cb=True, hydrogens=None):
    """
    Generate ATOM records for a chain.

    residues: list of (base_x, base_y, base_z) for each residue
    hydrogens: optional list of (name, x, y, z, resseq) hydrogen atoms to add
    """
    atoms_data = []  # list of dicts for Python computation
    lines = []       # PDB lines
    serial = [0]

    def add(nm, rn, x, y, z, el, is_h=False):
        serial[0] += 1
        lines.append(pdb_line(serial[0], nm, resname, chain_id, rn, x, y, z, el))
        if not is_h:
            atoms_data.append({
                'name': nm, 'resname': resname, 'chain': chain_id,
                'resseq': rn, 'coord': np.array([x, y, z]),
            })

    for i, (bx, by, bz) in enumerate(residues):
        rn = res_start + i
        add("N",  rn, bx,       by,       bz,       "N")
        add("CA", rn, bx + 1.5, by,       bz + 0.3, "C")
        add("C",  rn, bx + 2.0, by,       bz - 0.1, "C")
        add("O",  rn, bx + 2.0, by + 1.0, bz - 0.4, "O")
        if include_cb:
            add("CB", rn, bx + 1.5, by - 1.2, bz + 0.6, "C")

    if hydrogens:
        for nm, x, y, z, rn in hydrogens:
            serial[0] += 1
            lines.append(pdb_line(serial[0], nm, resname, chain_id, rn,
                                  x, y, z, "H"))
            # H atoms should NOT appear in atoms_data (they're filtered)

    return lines, atoms_data, serial[0]


def write_pdb(filepath, *chain_outputs):
    """Write PDB file from chain outputs. Returns combined atom list."""
    all_lines = []
    all_atoms = []
    for lines, atoms_data, _ in chain_outputs:
        all_lines.extend(lines)
        all_atoms.extend(atoms_data)
    all_lines.append("END")
    with open(filepath, 'w') as f:
        f.write('\n'.join(all_lines) + '\n')
    return all_atoms


def write_multimodel_pdb(filepath, models):
    """
    Write multi-model PDB file.

    models: list of (model_num, [chain_output1, chain_output2, ...])
    Returns: list of atom lists (one per model, for Python reference computation).
    """
    all_lines = []
    all_model_atoms = []
    for model_num, chain_list in models:
        all_lines.append(f"MODEL     {model_num:>4d}")
        model_atoms = []
        for lines, atoms_data, _ in chain_list:
            all_lines.extend(lines)
            model_atoms.extend(atoms_data)
        all_lines.append("ENDMDL")
        all_model_atoms.append(model_atoms)
    all_lines.append("END")
    with open(filepath, 'w') as f:
        f.write('\n'.join(all_lines) + '\n')
    return all_model_atoms


# ============================================================
# Python reference implementation of CAPRI metrics
# ============================================================

def py_compute_contacts(atoms, cutoff):
    """Compute inter-chain residue-level contacts."""
    contacts = set()
    for i, a1 in enumerate(atoms):
        for j in range(i + 1, len(atoms)):
            a2 = atoms[j]
            if a1['chain'] == a2['chain']:
                continue
            dist = np.linalg.norm(a1['coord'] - a2['coord'])
            if dist < cutoff:
                c1, r1 = a1['chain'], a1['resseq']
                c2, r2 = a2['chain'], a2['resseq']
                if c1 > c2 or (c1 == c2 and r1 > r2):
                    c1, r1, c2, r2 = c2, r2, c1, r1
                contacts.add((c1, r1, c2, r2))
    return contacts


def py_fnat(ref_atoms, model_atoms, cutoff):
    ref_c = py_compute_contacts(ref_atoms, cutoff)
    if not ref_c:
        return 0.0
    mod_c = py_compute_contacts(model_atoms, cutoff)
    return len(ref_c & mod_c) / len(ref_c)


def py_fnonnat(ref_atoms, model_atoms, cutoff):
    """Fraction of non-native contacts in model."""
    ref_c = py_compute_contacts(ref_atoms, cutoff)
    mod_c = py_compute_contacts(model_atoms, cutoff)
    if not mod_c:
        return 0.0
    non_native = len(mod_c - ref_c)
    return non_native / len(mod_c)


def py_kabsch(P, Q):
    """Kabsch rotation: find U s.t. P @ U ~= Q. P,Q are Nx3, centered."""
    C = P.T @ Q
    V, S, Wt = np.linalg.svd(C)
    d = np.linalg.det(V) * np.linalg.det(Wt)
    if d < 0:
        V[:, -1] *= -1
    return V @ Wt


def py_rmsd(P, Q):
    diff = P - Q
    return np.sqrt(np.sum(diff ** 2) / len(P))


def py_irmsd(ref_atoms, model_atoms, cutoff):
    contacts = py_compute_contacts(ref_atoms, cutoff)
    interface = {}
    for c in contacts:
        interface.setdefault(c[0], set()).add(c[1])
        interface.setdefault(c[2], set()).add(c[3])

    if not interface:
        return -1.0

    # Build model lookup
    mod_map = {}
    for a in model_atoms:
        if a['name'] not in ('N', 'CA', 'C', 'O'):
            continue
        mod_map[(a['chain'], a['resseq'], a['name'])] = a['coord']

    ref_coords, mod_coords = [], []
    for a in ref_atoms:
        if a['name'] not in ('N', 'CA', 'C', 'O'):
            continue
        if a['chain'] not in interface:
            continue
        if a['resseq'] not in interface[a['chain']]:
            continue
        key = (a['chain'], a['resseq'], a['name'])
        if key in mod_map:
            ref_coords.append(a['coord'])
            mod_coords.append(mod_map[key])

    if len(ref_coords) < 3:
        return -1.0

    Q = np.array(ref_coords)
    P = np.array(mod_coords)
    Q = Q - Q.mean(axis=0)
    P = P - P.mean(axis=0)
    U = py_kabsch(P, Q)
    P = P @ U
    return py_rmsd(P, Q)


def py_lrmsd(ref_atoms, model_atoms, receptor_chain, ligand_chains):
    mod_map = {}
    for a in model_atoms:
        if a['name'] not in ('N', 'CA', 'C', 'O'):
            continue
        mod_map[(a['chain'], a['resseq'], a['name'])] = a['coord']

    ref_r, mod_r, ref_l, mod_l = [], [], [], []
    for a in ref_atoms:
        if a['name'] not in ('N', 'CA', 'C', 'O'):
            continue
        key = (a['chain'], a['resseq'], a['name'])
        if key not in mod_map:
            continue
        if a['chain'] == receptor_chain:
            ref_r.append(a['coord'])
            mod_r.append(mod_map[key])
        elif a['chain'] in ligand_chains:
            ref_l.append(a['coord'])
            mod_l.append(mod_map[key])

    if len(ref_r) < 3 or not ref_l:
        return -1.0

    nR = len(ref_r)
    Q = np.vstack(ref_r + ref_l)
    P = np.vstack(mod_r + mod_l)

    # Center by receptor centroid
    Q_r_cent = Q[:nR].mean(axis=0)
    P_r_cent = P[:nR].mean(axis=0)
    Q = Q - Q_r_cent
    P = P - P_r_cent

    # Kabsch on receptor
    U = py_kabsch(P[:nR], Q[:nR])
    P = P @ U

    # RMSD of ligand only
    return py_rmsd(P[nR:], Q[nR:])


def py_dockq(fnat, irmsd, lrmsd):
    return (fnat / 3.0 +
            (1.0 / (1.0 + (irmsd / 1.5) ** 2)) / 3.0 +
            (1.0 / (1.0 + (lrmsd / 8.5) ** 2)) / 3.0)


def py_classify(fnat, irmsd, lrmsd):
    if fnat >= 0.5 and (lrmsd <= 1.0 or irmsd <= 1.0):
        return "High"
    if fnat >= 0.3 and (lrmsd <= 5.0 or irmsd <= 2.0):
        return "Medium"
    if fnat >= 0.1 and (lrmsd <= 10.0 or irmsd <= 4.0):
        return "Acceptable"
    return "Incorrect"


# ============================================================
# Run the C++ binary and parse output
# ============================================================

def run_scorer(ref_path, mod_path, rec_chain, lig_chains, cutoff=5.0):
    """Run the C++ scorer and return parsed output dict."""
    cmd = [BINARY, ref_path, mod_path, rec_chain, lig_chains, str(cutoff)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"Scorer failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    output = {}
    for line in result.stdout.strip().split('\n'):
        if '=' in line:
            key, val = line.split('=', 1)
            key = key.strip()
            try:
                output[key] = float(val)
            except ValueError:
                output[key] = val.strip()
    return output


# ============================================================
# Test fixture: compile the binary
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def compile_binary():
    """Ensure the C++ binary is compiled."""
    if not os.path.isfile(BINARY):
        result = subprocess.run(
            ["make", "-C", "/app"], capture_output=True, text=True
        )
        if result.returncode != 0:
            pytest.fail(
                f"Compilation failed:\n{result.stdout}\n{result.stderr}"
            )
    assert os.path.isfile(BINARY), f"Binary {BINARY} not found after make"


# ============================================================
# Test 1: Perfect model (identical to reference)
# ============================================================

def test_perfect_model():
    """When model == reference, fnat=1, fnonnat=0, irmsd=0, lrmsd=0, dockq=1, quality=High."""
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        # Chain A: receptor (6 residues)
        a_res = [(0, 0, 0), (4, 0, 0.5), (8, 0, -0.3),
                 (12, 0, 0.2), (16, 0, -0.4), (20, 0, 0.1)]
        # Chain B: ligand (4 residues)
        b_res = [(14, 4.5, 0.3), (18, 4.5, -0.2),
                 (22, 4.5, 0.5), (26, 4.5, -0.1)]

        chain_a = make_chain("A", a_res)
        chain_b = make_chain("B", b_res)
        ref_atoms = write_pdb(ref_path, chain_a, chain_b)
        mod_atoms = write_pdb(mod_path, chain_a, chain_b)  # identical

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert abs(out['fnat'] - 1.0) < TOLERANCE
        assert abs(out['fnonnat'] - 0.0) < TOLERANCE
        assert abs(out['irmsd']) < TOLERANCE
        assert abs(out['lrmsd']) < TOLERANCE
        assert abs(out['dockq'] - 1.0) < TOLERANCE
        assert out['quality'] == "High"
        assert 'model' not in out, "Single model should not output model= line"


# ============================================================
# Test 2: Translated ligand
# ============================================================

def test_translated_ligand():
    """Chain B uniformly translated. Verify all metrics including fnonnat."""
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0), (4, 0, 0.5), (8, 0, -0.3),
                 (12, 0, 0.2), (16, 0, -0.4), (20, 0, 0.1)]
        b_res = [(14, 4.5, 0.3), (18, 4.5, -0.2),
                 (22, 4.5, 0.5), (26, 4.5, -0.1)]

        dx, dy, dz = 0.5, 0.3, 0.2
        b_res_shifted = [(x + dx, y + dy, z + dz) for x, y, z in b_res]

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_shifted)

        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        # Compute expected values
        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
        exp_irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
        exp_lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
        exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)
        exp_quality = py_classify(exp_fnat, exp_irmsd, exp_lrmsd)

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat}"
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
        assert abs(out['irmsd'] - exp_irmsd) < TOLERANCE, \
            f"irmsd: got {out['irmsd']}, expected {exp_irmsd}"
        assert abs(out['lrmsd'] - exp_lrmsd) < TOLERANCE, \
            f"lrmsd: got {out['lrmsd']}, expected {exp_lrmsd}"
        assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
            f"dockq: got {out['dockq']}, expected {exp_dockq}"
        assert out['quality'] == exp_quality, \
            f"quality: got {out['quality']}, expected {exp_quality}"


# ============================================================
# Test 3: Rotated + translated ligand (exercises Kabsch deeply)
# ============================================================

def test_rotated_ligand():
    """Chain B rotated and translated. Tests Kabsch superposition thoroughly."""
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0.0), (4, 0, 1.0), (8, 0, -1.0),
                 (12, 0, 0.5), (16, 0, -0.5), (20, 0, 0.3)]
        b_res = [(14, 5.0, 0.8), (18, 5.0, -0.5),
                 (22, 5.0, 1.2), (26, 5.0, -0.3)]

        # Apply a rotation around Z axis (15 degrees) + translation to chain B
        theta = math.radians(15)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        tx, ty, tz = 1.0, 0.5, 0.3

        b_res_transformed = []
        for bx, by, bz in b_res:
            # Rotate around the centroid of b_res
            cx = sum(x for x, _, _ in b_res) / len(b_res)
            cy = sum(y for _, y, _ in b_res) / len(b_res)
            cz = sum(z for _, _, z in b_res) / len(b_res)
            rx = (bx - cx) * cos_t - (by - cy) * sin_t + cx + tx
            ry = (bx - cx) * sin_t + (by - cy) * cos_t + cy + ty
            rz = bz + tz
            b_res_transformed.append((rx, ry, rz))

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_transformed)

        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
        exp_irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
        exp_lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
        exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)
        exp_quality = py_classify(exp_fnat, exp_irmsd, exp_lrmsd)

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat}"
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
        assert abs(out['irmsd'] - exp_irmsd) < TOLERANCE, \
            f"irmsd: got {out['irmsd']}, expected {exp_irmsd}"
        assert abs(out['lrmsd'] - exp_lrmsd) < TOLERANCE, \
            f"lrmsd: got {out['lrmsd']}, expected {exp_lrmsd}"
        assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
            f"dockq: got {out['dockq']}, expected {exp_dockq}"
        assert out['quality'] == exp_quality, \
            f"quality: got {out['quality']}, expected {exp_quality}"


# ============================================================
# Test 4: Hydrogen filtering (old-style numbered H names)
# ============================================================

def test_hydrogen_filtering():
    """
    Chains placed far apart so NO heavy-atom inter-chain contacts exist.
    Old-style numbered H atoms (1HB, 2HG) are placed between chains.
    With correct H filter: no contacts, fnat = 0.0, fnonnat = 0.0
    With broken H filter: spurious contacts
    """
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        # Chains far apart (y=12 separation) - no heavy-atom contacts
        a_res = [(0, 0, 0), (4, 0, 0.3), (8, 0, -0.2)]
        b_res = [(9, 12, 0.1), (13, 12, -0.3)]

        # Old-style H atoms positioned in the gap between chains
        a_hydrogens = [
            ("1HB", 8.5, 8.0, 0.0, 3),
            ("2HG", 9.0, 9.0, 0.0, 3),
            ("H",   8.5, -0.5, 0.0, 3),
        ]
        b_hydrogens = [
            ("1HB", 10.0, 10.0, 0.0, 1),
            ("H",   9.5, 12.5, 0.0, 1),
        ]

        chain_a = make_chain("A", a_res, hydrogens=a_hydrogens)
        chain_b = make_chain("B", b_res, hydrogens=b_hydrogens)
        ref_atoms = write_pdb(ref_path, chain_a, chain_b)

        # Model: identical
        chain_a2 = make_chain("A", a_res, hydrogens=a_hydrogens)
        chain_b2 = make_chain("B", b_res, hydrogens=b_hydrogens)
        mod_atoms = write_pdb(mod_path, chain_a2, chain_b2)

        # Python reference (H atoms excluded from atoms_data): fnat = 0.0
        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        assert exp_fnat == 0.0, \
            f"Sanity: expected no heavy-atom contacts, got fnat={exp_fnat}"

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat} (hydrogen filtering issue)"
        assert abs(out['fnonnat'] - 0.0) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected 0.0"


# ============================================================
# Test 5: Large displacement (Incorrect quality)
# ============================================================

def test_incorrect_quality():
    """Large displacement should produce quality=Incorrect."""
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0), (4, 0, 0.5), (8, 0, -0.3),
                 (12, 0, 0.2), (16, 0, -0.4), (20, 0, 0.1)]
        b_res = [(14, 4.5, 0.3), (18, 4.5, -0.2),
                 (22, 4.5, 0.5), (26, 4.5, -0.1)]

        # Shift chain B far away
        dx, dy, dz = 15.0, 10.0, 5.0
        b_res_far = [(x + dx, y + dy, z + dz) for x, y, z in b_res]

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_far)

        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
        exp_quality = py_classify(
            exp_fnat,
            py_irmsd(ref_atoms, mod_atoms, CUTOFF),
            py_lrmsd(ref_atoms, mod_atoms, "A", "B"),
        )

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert out['quality'] == "Incorrect", \
            f"quality: got {out['quality']}, expected Incorrect"
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE


# ============================================================
# Test 6: Quality classification boundary (OR logic)
# ============================================================

def test_quality_or_logic():
    """
    Test that classification uses OR for lrmsd/irmsd conditions.
    """
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        # Dense interface geometry
        a_res = [(0, 0, 0), (3, 0, 0.5), (6, 0, -0.3),
                 (9, 0, 0.2), (12, 0, -0.4)]
        b_res = [(3, 3.5, 0.3), (6, 3.5, -0.2),
                 (9, 3.5, 0.5), (12, 3.5, -0.1)]

        dx, dy, dz = 2.0, -1.5, 0.8
        b_res_shifted = [(x + dx, y + dy, z + dz) for x, y, z in b_res]

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_shifted)

        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
        exp_irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
        exp_lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
        exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)
        exp_quality = py_classify(exp_fnat, exp_irmsd, exp_lrmsd)

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat}"
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
        assert abs(out['irmsd'] - exp_irmsd) < TOLERANCE, \
            f"irmsd: got {out['irmsd']}, expected {exp_irmsd}"
        assert abs(out['lrmsd'] - exp_lrmsd) < TOLERANCE, \
            f"lrmsd: got {out['lrmsd']}, expected {exp_lrmsd}"
        assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
            f"dockq: got {out['dockq']}, expected {exp_dockq}"
        assert out['quality'] == exp_quality, \
            f"quality: got {out['quality']}, expected {exp_quality}"


# ============================================================
# Test 7: DockQ formula constants
# ============================================================

def test_dockq_values():
    """Verify DockQ formula uses correct constants (1.5 and 8.5)."""
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0), (4, 0, 0.5), (8, 0, -0.3),
                 (12, 0, 0.2), (16, 0, -0.4), (20, 0, 0.1)]
        b_res = [(14, 4.5, 0.3), (18, 4.5, -0.2),
                 (22, 4.5, 0.5), (26, 4.5, -0.1)]

        dx, dy, dz = 1.0, 0.8, 0.5
        b_res_shifted = [(x + dx, y + dy, z + dz) for x, y, z in b_res]

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_shifted)

        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
        exp_irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
        exp_lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
        exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)

        # Also compute with wrong constants to make sure it's NOT those
        wrong_dockq = (exp_fnat / 3.0 +
                       (1.0 / (1.0 + (exp_irmsd / 1.0) ** 2)) / 3.0 +
                       (1.0 / (1.0 + (exp_lrmsd / 5.0) ** 2)) / 3.0)

        out = run_scorer(ref_path, mod_path, "A", "B")

        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
        assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
            f"dockq: got {out['dockq']}, expected {exp_dockq}"
        # Ensure it's NOT using the wrong constants
        if abs(exp_dockq - wrong_dockq) > 0.01:
            assert abs(out['dockq'] - wrong_dockq) > 0.01, \
                f"dockq appears to use wrong constants (1.0, 5.0)"


# ============================================================
# Test 8: Sample data from environment
# ============================================================

def test_sample_data():
    """Run on the provided sample data files and verify against Python reference."""
    ref_path = "/app/data/reference.pdb"
    mod_path = "/app/data/model.pdb"

    if not os.path.isfile(ref_path) or not os.path.isfile(mod_path):
        pytest.skip("Sample data files not found")

    # Parse PDB files in Python to get expected values
    def parse_pdb_py(filepath):
        atoms = []
        with open(filepath) as f:
            for line in f:
                if not line.startswith("ATOM"):
                    continue
                if len(line) < 54:
                    continue
                name = line[12:16].strip()
                # Filter hydrogens
                if name and name[0] == 'H':
                    continue
                if name and len(name) > 1 and name[0].isdigit() and name[1] == 'H':
                    continue
                resname = line[17:20].strip()
                chain = line[21]
                resseq = int(line[22:26])
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                atoms.append({
                    'name': name, 'resname': resname, 'chain': chain,
                    'resseq': resseq, 'coord': np.array([x, y, z]),
                })
        return atoms

    ref_atoms = parse_pdb_py(ref_path)
    mod_atoms = parse_pdb_py(mod_path)

    exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
    exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
    exp_irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
    exp_lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
    exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)
    exp_quality = py_classify(exp_fnat, exp_irmsd, exp_lrmsd)

    out = run_scorer(ref_path, mod_path, "A", "B")
    assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
        f"fnat: got {out['fnat']}, expected {exp_fnat}"
    assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
        f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
    assert abs(out['irmsd'] - exp_irmsd) < TOLERANCE, \
        f"irmsd: got {out['irmsd']}, expected {exp_irmsd}"
    assert abs(out['lrmsd'] - exp_lrmsd) < TOLERANCE, \
        f"lrmsd: got {out['lrmsd']}, expected {exp_lrmsd}"
    assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
        f"dockq: got {out['dockq']}, expected {exp_dockq}"
    assert out['quality'] == exp_quality, \
        f"quality: got {out['quality']}, expected {exp_quality}"


# ============================================================
# Test 9: f-nonnat with non-native contacts
# ============================================================

def test_fnonnat_nonnative():
    """
    Model has contacts not present in reference.
    Reference has B:2 far away (no contacts). Model has B:2 close to A
    (creating non-native contacts). fnonnat should be > 0.
    """
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0), (4, 0, 0), (8, 0, 0)]
        b_res_ref = [(2, 4, 0), (40, 4, 0)]     # B:2 far away in reference
        b_res_mod = [(2, 4, 0), (6, 4, 0)]       # B:2 near A:2/A:3 in model

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res_ref)
        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)

        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_mod)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)

        # Sanity: model should have non-native contacts
        ref_contacts = py_compute_contacts(ref_atoms, CUTOFF)
        mod_contacts = py_compute_contacts(mod_atoms, CUTOFF)
        assert len(mod_contacts - ref_contacts) > 0, \
            "Sanity: model should have contacts not in reference"
        assert exp_fnonnat > 0.0, \
            f"Sanity: expected positive fnonnat, got {exp_fnonnat}"

        out = run_scorer(ref_path, mod_path, "A", "B")
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat}"
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"


# ============================================================
# Test 10: Multi-model PDB — best DockQ selection
# ============================================================

def test_multimodel_best_dockq():
    """
    Model PDB with 3 MODEL/ENDMDL blocks. Verify the scorer selects
    the model with the highest DockQ and outputs model=N.
    """
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0), (4, 0, 0.5), (8, 0, -0.3),
                 (12, 0, 0.2), (16, 0, -0.4), (20, 0, 0.1)]
        b_res = [(14, 4.5, 0.3), (18, 4.5, -0.2),
                 (22, 4.5, 0.5), (26, 4.5, -0.1)]

        # Write reference (single model)
        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)

        # Model 1: large shift (bad DockQ)
        b_shift1 = [(x + 5, y + 5, z + 3) for x, y, z in b_res]
        # Model 2: tiny shift (best DockQ)
        b_shift2 = [(x + 0.3, y + 0.1, z + 0.1) for x, y, z in b_res]
        # Model 3: medium shift
        b_shift3 = [(x + 2, y + 1.5, z + 0.8) for x, y, z in b_res]

        # Write multi-model PDB
        models_data = [
            (1, [make_chain("A", a_res), make_chain("B", b_shift1)]),
            (2, [make_chain("A", a_res), make_chain("B", b_shift2)]),
            (3, [make_chain("A", a_res), make_chain("B", b_shift3)]),
        ]
        all_model_atoms = write_multimodel_pdb(mod_path, models_data)

        # Compute DockQ for each model using Python reference
        dockqs = []
        for i, mod_atoms in enumerate(all_model_atoms):
            fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
            irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
            lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
            dq = py_dockq(fnat, irmsd, lrmsd)
            dockqs.append((i, dq))

        best_idx = max(dockqs, key=lambda x: x[1])[0]
        best_model_num = models_data[best_idx][0]
        best_atoms = all_model_atoms[best_idx]

        exp_fnat = py_fnat(ref_atoms, best_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, best_atoms, CUTOFF)
        exp_irmsd = py_irmsd(ref_atoms, best_atoms, CUTOFF)
        exp_lrmsd = py_lrmsd(ref_atoms, best_atoms, "A", "B")
        exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)
        exp_quality = py_classify(exp_fnat, exp_irmsd, exp_lrmsd)

        out = run_scorer(ref_path, mod_path, "A", "B")

        # Verify model selection
        assert 'model' in out, "Multi-model output should include model= line"
        assert int(out['model']) == best_model_num, \
            f"model: got {int(out['model'])}, expected {best_model_num}"

        # Verify metrics match best model
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat}"
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
        assert abs(out['irmsd'] - exp_irmsd) < TOLERANCE, \
            f"irmsd: got {out['irmsd']}, expected {exp_irmsd}"
        assert abs(out['lrmsd'] - exp_lrmsd) < TOLERANCE, \
            f"lrmsd: got {out['lrmsd']}, expected {exp_lrmsd}"
        assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
            f"dockq: got {out['dockq']}, expected {exp_dockq}"
        assert out['quality'] == exp_quality, \
            f"quality: got {out['quality']}, expected {exp_quality}"


# ============================================================
# Test 11: Single model — no model= line in output
# ============================================================

def test_singlemodel_no_model_line():
    """Single model PDB without MODEL/ENDMDL: output should NOT have model= line."""
    with tempfile.TemporaryDirectory() as td:
        ref_path = os.path.join(td, "ref.pdb")
        mod_path = os.path.join(td, "mod.pdb")

        a_res = [(0, 0, 0), (4, 0, 0.5), (8, 0, -0.3),
                 (12, 0, 0.2), (16, 0, -0.4), (20, 0, 0.1)]
        b_res = [(14, 4.5, 0.3), (18, 4.5, -0.2),
                 (22, 4.5, 0.5), (26, 4.5, -0.1)]

        dx, dy, dz = 0.8, 0.4, 0.3
        b_res_shifted = [(x + dx, y + dy, z + dz) for x, y, z in b_res]

        chain_a_ref = make_chain("A", a_res)
        chain_b_ref = make_chain("B", b_res)
        chain_a_mod = make_chain("A", a_res)
        chain_b_mod = make_chain("B", b_res_shifted)

        ref_atoms = write_pdb(ref_path, chain_a_ref, chain_b_ref)
        mod_atoms = write_pdb(mod_path, chain_a_mod, chain_b_mod)

        exp_fnat = py_fnat(ref_atoms, mod_atoms, CUTOFF)
        exp_fnonnat = py_fnonnat(ref_atoms, mod_atoms, CUTOFF)
        exp_irmsd = py_irmsd(ref_atoms, mod_atoms, CUTOFF)
        exp_lrmsd = py_lrmsd(ref_atoms, mod_atoms, "A", "B")
        exp_dockq = py_dockq(exp_fnat, exp_irmsd, exp_lrmsd)

        out = run_scorer(ref_path, mod_path, "A", "B")

        assert 'model' not in out, \
            "Single model should not have model= in output"
        assert abs(out['fnat'] - exp_fnat) < TOLERANCE, \
            f"fnat: got {out['fnat']}, expected {exp_fnat}"
        assert abs(out['fnonnat'] - exp_fnonnat) < TOLERANCE, \
            f"fnonnat: got {out['fnonnat']}, expected {exp_fnonnat}"
        assert abs(out['irmsd'] - exp_irmsd) < TOLERANCE, \
            f"irmsd: got {out['irmsd']}, expected {exp_irmsd}"
        assert abs(out['lrmsd'] - exp_lrmsd) < TOLERANCE, \
            f"lrmsd: got {out['lrmsd']}, expected {exp_lrmsd}"
        assert abs(out['dockq'] - exp_dockq) < TOLERANCE, \
            f"dockq: got {out['dockq']}, expected {exp_dockq}"
