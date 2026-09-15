#!/usr/bin/env python3
"""
Protein pKa prediction engine based on the PROPKA empirical model.
Implements standalone energy functions and wraps PROPKA for the full pipeline.
"""
import json
import math
import os
import sys
import re
import io
import logging
import tempfile


# ============================================================
# Standalone energy / calculation functions
# ============================================================

def hydrogen_bond_energy(dist, dpka_max, cutoffs, f_angle=1.0):
    """Hydrogen bond pKa shift: linear interpolation between cutoffs."""
    if dist < cutoffs[0]:
        value = 1.0
    elif dist > cutoffs[1]:
        value = 0.0
    else:
        value = 1.0 - (dist - cutoffs[0]) / (cutoffs[1] - cutoffs[0])
    dpka = dpka_max * value * f_angle
    return abs(dpka)


def coulomb_energy(dist, weight, coulomb_cutoff1=4.0, coulomb_cutoff2=10.0):
    """Coulomb pKa shift with distance-dependent dielectric."""
    diel = 160.0 - (160.0 - 30.0) * weight
    dist = max(dist, coulomb_cutoff1)
    scale = (dist - coulomb_cutoff2) / (coulomb_cutoff1 - coulomb_cutoff2)
    scale = max(0.0, min(1.0, scale))
    dpka = 244.12 / (diel * dist) * scale
    return abs(dpka)


def calculate_burial_weight(num_volume, nmin=280, nmax=560):
    """Atom-based desolvation weight, clamped to [0, 1]."""
    weight = float(num_volume - nmin) / float(nmax - nmin)
    return max(0.0, min(1.0, weight))


def calculate_scale_factor(weight, surface_scaling_factor=0.25):
    """Desolvation surface scaling factor."""
    return 1.0 - (1.0 - surface_scaling_factor) * (1.0 - weight)


def calculate_residue_charge(pka, ph, charge_sign):
    """Fractional charge for a single titratable group."""
    q_dpka = charge_sign * (pka - ph)
    if q_dpka > 300:
        return float(charge_sign)
    elif q_dpka < -300:
        return 0.0
    conc_ratio = 10.0 ** q_dpka
    return charge_sign * (conc_ratio / (1.0 + conc_ratio))


def find_isoelectric_point(pka_charge_pairs, ph_min=0.0, ph_max=14.0,
                           precision=1e-4):
    """Find pH of zero net charge via bisection."""
    def total_charge(ph):
        return sum(
            calculate_residue_charge(pka, ph, cs)
            for pka, cs in pka_charge_pairs
        )
    lo, hi = ph_min, ph_max
    while hi - lo > precision:
        mid = (lo + hi) / 2.0
        if total_charge(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def compute_net_charge(pka_charge_pairs, ph):
    """Total net charge across all groups at given pH."""
    return sum(
        calculate_residue_charge(pka, ph, cs)
        for pka, cs in pka_charge_pairs
    )


# ============================================================
# Full pipeline using propka with .pka file parsing
# ============================================================

def _parse_pka_file(pka_path):
    """Parse pKa values and pI from a PROPKA .pka output file.

    Uses the same parsing logic as PROPKA's own regression tests.
    """
    pka_values = []
    pi_folded = None
    pi_unfolded = None

    with open(pka_path, 'rt') as fh:
        at_pka = False
        for line in fh:
            if at_pka:
                if line.startswith('---'):
                    at_pka = False
                else:
                    m = re.search(r'\d+\.\d+', line[13:])
                    if m is not None:
                        pka_values.append(float(m.group()))
            elif 'model-pKa' in line:
                at_pka = True
            else:
                m = re.match(
                    r'The pI is\s+(\d+\.\d+)\s+\(folded\)\s+and\s+'
                    r'(\d+\.\d+)\s+\(unfolded\)',
                    line)
                if m is not None:
                    pi_folded = float(m.group(1))
                    pi_unfolded = float(m.group(2))

    return pka_values, pi_folded, pi_unfolded


def run_pipeline(pdb_path):
    """Run PROPKA on a PDB file and return results as dict.

    Suppresses all stdout/stderr from propka and parses the .pka output file
    to extract values (matching PROPKA's own test methodology).
    """
    # Save real stdout/stderr and suppress everything during propka execution
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    logging.disable(logging.CRITICAL)

    try:
        import propka.run

        abs_pdb_path = os.path.abspath(pdb_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                propka.run.single(abs_pdb_path)
            finally:
                os.chdir(orig_dir)

            # Parse the .pka output file
            pdb_stem = os.path.splitext(os.path.basename(pdb_path))[0]
            pka_path = os.path.join(tmpdir, '{0:s}.pka'.format(pdb_stem))
            pka_values, pi_folded, pi_unfolded = _parse_pka_file(pka_path)
    finally:
        sys.stdout = real_stdout
        sys.stderr = real_stderr
        logging.disable(logging.NOTSET)

    return {
        'pka_values': pka_values,
        'pi_folded': pi_folded,
        'pi_unfolded': pi_unfolded,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 pka_engine.py <pdb_file>", file=sys.stderr)
        sys.exit(1)

    pdb_path = sys.argv[1]
    if not os.path.exists(pdb_path):
        print("Error: PDB file not found: {0:s}".format(pdb_path),
              file=sys.stderr)
        sys.exit(1)

    result = run_pipeline(pdb_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
