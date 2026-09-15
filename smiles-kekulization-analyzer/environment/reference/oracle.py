#!/usr/bin/env python3
"""
Reference oracle for SMILES analysis using RDKit.

Usage:
  echo "c1ccccc1" | python3 /app/reference/oracle.py
  python3 /app/reference/oracle.py < smiles.txt

Reads SMILES from stdin, outputs JSON per line.
Does NOT compute the tautomer_hash field.
Error classification may differ from the target in edge cases.
"""

import sys
import json

try:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False


def analyze(smi):
    result = {
        "smiles": smi,
        "valid": False,
        "error_type": None,
        "num_heavy_atoms": None,
        "implicit_hydrogens": None,
        "molecular_formula": None,
        "kekulizable": None,
        "tautomer_hash": None
    }

    if not RDKIT_AVAILABLE:
        result["error_type"] = "oracle_unavailable"
        return result

    mol = Chem.MolFromSmiles(smi, sanitize=False)
    if mol is None:
        result["error_type"] = "syntax"
        return result

    try:
        Chem.SanitizeMol(mol)
    except Exception as e:
        emsg = str(e).lower()
        if "kekul" in emsg:
            result["error_type"] = "kekulization"
        elif "valence" in emsg:
            result["error_type"] = "valence"
        else:
            result["error_type"] = "syntax"
        return result

    result["valid"] = True
    result["num_heavy_atoms"] = mol.GetNumHeavyAtoms()
    result["implicit_hydrogens"] = [
        atom.GetTotalNumHs() for atom in mol.GetAtoms()
    ]
    result["molecular_formula"] = rdMolDescriptors.CalcMolFormula(mol)

    has_arom = any(atom.GetIsAromatic() for atom in mol.GetAtoms())
    result["kekulizable"] = True if has_arom else None

    return result


if __name__ == "__main__":
    if not RDKIT_AVAILABLE:
        print("Warning: rdkit not available", file=sys.stderr)

    for line in sys.stdin:
        smi = line.strip()
        if smi:
            print(json.dumps(analyze(smi)))
