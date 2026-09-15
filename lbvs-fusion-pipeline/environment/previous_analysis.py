#!/usr/bin/env python3
"""VS benchmarking analysis - DRAFT
Results look anomalous, needs review before finalizing."""

import json
import numpy as np
from skfp.preprocessing import MolFromSmilesTransformer
from skfp.model_selection import randomized_scaffold_train_test_split
from skfp.fingerprints import ECFPFingerprint, AtomPairFingerprint, MACCSFingerprint
from skfp.distances import bulk_tanimoto_binary_similarity
from skfp.metrics import bedroc_score, enrichment_factor

with open("/app/data/bace.json") as f:
    data = json.load(f)

smiles = data["smiles"]
y = np.array(data["labels"])

config = json.load(open("/app/task_config.json"))

transformer = MolFromSmilesTransformer(valid_only=True)
mols, y = transformer.transform_x_y(smiles, y)

# Quick test with first seed only
seed = config["seed_values"][0]
mols_train, mols_test, y_train, y_test = randomized_scaffold_train_test_split(
    mols, y, test_size=config["test_size"], random_state=seed
)

# Compute ECFP similarity scores
fp = ECFPFingerprint()
X_train = fp.transform(mols_train)
X_test = fp.transform(mols_test)

sims = bulk_tanimoto_binary_similarity(X_train, X_test)
scores = np.max(sims, axis=0)

b = bedroc_score(y_test, scores, alpha=config["bedroc_alpha"])
ef = enrichment_factor(y_test, scores, fraction=config["ef_percentage"])

print(f"ECFP BEDROC: {b:.4f}, EF: {ef:.4f}")
print("TODO: remaining fingerprints, fusion strategies, full multi-split analysis")
