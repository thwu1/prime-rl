"""Download and cache the BACE dataset from MoleculeNet via scikit-fingerprints."""
import json
import os
from skfp.datasets.moleculenet import load_bace

smiles, y = load_bace()
os.makedirs("/app/data", exist_ok=True)
with open("/app/data/bace.json", "w") as f:
    json.dump({"smiles": list(smiles), "labels": y.tolist()}, f)
print(f"BACE dataset saved: {len(smiles)} molecules")
