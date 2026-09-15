#!/usr/bin/env python3
"""
Solution for regulatory network reconstruction from multi-omic data.

Pipeline:
1. Parse MEME-format motifs and scan promoters for binding sites
2. Use bedtools intersect to filter by chromatin accessibility
3. Fit main-effects regression model for expression prediction
4. Analyze residuals to discover TF-TF cooperative interactions
5. Output regulatory network, predictions, and functional binding sites

"""

import json
import math
import os
import re
import subprocess
import tempfile

import numpy as np
from sklearn.linear_model import Ridge

BASE_TO_IDX = {"A": 0, "C": 1, "G": 2, "T": 3}
COMP = {"A": "T", "C": "G", "G": "C", "T": "A", "N": "N"}

DATA_DIR = "/app/data"
RESULTS_DIR = "/app/results"


def reverse_complement(seq):
    return "".join(COMP[b] for b in reversed(seq))


def parse_meme_motifs(path):
    motifs = {}
    current_name = None
    current_pwm = []
    reading_matrix = False
    with open(path) as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("MOTIF"):
                if current_name and current_pwm:
                    motifs[current_name] = {"pwm": current_pwm, "length": len(current_pwm)}
                parts = line.split()
                current_name = parts[1] if len(parts) >= 2 else None
                current_pwm = []
                reading_matrix = False
            elif line.startswith("letter-probability matrix"):
                reading_matrix = True
            elif reading_matrix and line.strip():
                vals = line.strip().split()
                if len(vals) == 4:
                    try:
                        current_pwm.append([float(v) for v in vals])
                    except ValueError:
                        reading_matrix = False
            elif reading_matrix and not line.strip():
                reading_matrix = False
    if current_name and current_pwm:
        motifs[current_name] = {"pwm": current_pwm, "length": len(current_pwm)}
    return motifs


def parse_fasta(path):
    sequences = {}
    current_id = None
    current_seq = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_id is not None:
                    sequences[current_id] = "".join(current_seq)
                current_id = line[1:].split()[0]
                current_seq = []
            else:
                current_seq.append(line.upper())
    if current_id is not None:
        sequences[current_id] = "".join(current_seq)
    return sequences


def estimate_background(sequences):
    counts = np.zeros(4)
    for seq in sequences.values():
        for base in seq:
            if base in BASE_TO_IDX:
                counts[BASE_TO_IDX[base]] += 1
    total = counts.sum()
    return counts / total if total > 0 else np.full(4, 0.25)


def pwm_to_log_odds(pwm, bg_freq):
    return [[math.log2(max(p, 1e-6) / max(bg_freq[i], 1e-6))
             for i, p in enumerate(pos)] for pos in pwm]


def score_subseq(subseq, log_odds):
    score = 0.0
    for i, base in enumerate(subseq):
        if base not in BASE_TO_IDX:
            return -1000.0
        score += log_odds[i][BASE_TO_IDX[base]]
    return score


def scan_sequence(seq, log_odds, threshold):
    motif_len = len(log_odds)
    sites = []
    for i in range(len(seq) - motif_len + 1):
        sub = seq[i:i + motif_len]
        fwd = score_subseq(sub, log_odds)
        if fwd >= threshold:
            sites.append((i, i + motif_len, fwd, "+"))
            continue
        rc = reverse_complement(sub)
        rev = score_subseq(rc, log_odds)
        if rev >= threshold:
            sites.append((i, i + motif_len, rev, "-"))
    return sites


def intersect_with_accessibility(sites_bed_lines, acc_path):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bed", delete=False) as tmp:
        tmp_path = tmp.name
        for line in sites_bed_lines:
            tmp.write(line + "\n")
    try:
        result = subprocess.run(
            ["bedtools", "intersect", "-a", tmp_path, "-b", acc_path, "-wa", "-u"],
            capture_output=True, text=True, check=True,
        )
        return [l for l in result.stdout.strip().split("\n") if l.strip()]
    finally:
        os.unlink(tmp_path)


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    motifs = parse_meme_motifs(os.path.join(DATA_DIR, "motifs.meme"))
    tf_names = sorted(motifs.keys())
    print(f"Loaded {len(tf_names)} TF motifs: {tf_names}")

    train_seqs = parse_fasta(os.path.join(DATA_DIR, "promoters_train.fa"))
    test_seqs = parse_fasta(os.path.join(DATA_DIR, "promoters_test.fa"))
    all_seqs = {**train_seqs, **test_seqs}
    print(f"Train: {len(train_seqs)}, Test: {len(test_seqs)}")

    train_expr = {}
    with open(os.path.join(DATA_DIR, "expression_train.tsv")) as f:
        f.readline()
        for line in f:
            parts = line.strip().split("\t")
            train_expr[parts[0]] = float(parts[1])

    bg_freq = estimate_background(all_seqs)

    # Build log-odds matrices and thresholds
    log_odds = {}
    thresholds = {}
    for tf in tf_names:
        lo = pwm_to_log_odds(motifs[tf]["pwm"], bg_freq)
        log_odds[tf] = lo
        max_score = sum(max(pos) for pos in lo)
        thresholds[tf] = max_score * 0.65

    # Scan all promoters
    all_sites_bed = []
    for gid in sorted(all_seqs.keys()):
        seq = all_seqs[gid].upper()
        for tf in tf_names:
            for start, end, score, strand in scan_sequence(seq, log_odds[tf], thresholds[tf]):
                all_sites_bed.append(f"{gid}\t{start}\t{end}\t{tf}\t{score:.3f}\t{strand}")

    print(f"Total binding sites: {len(all_sites_bed)}")

    # Filter by accessibility using bedtools
    acc_path = os.path.join(DATA_DIR, "accessibility.bed")
    functional_lines = intersect_with_accessibility(all_sites_bed, acc_path)
    print(f"Functional sites (accessible): {len(functional_lines)}")

    # Count functional binding sites per gene per TF
    gene_tf_counts = {gid: {tf: 0 for tf in tf_names} for gid in all_seqs}
    for line in functional_lines:
        parts = line.split("\t")
        gene_tf_counts[parts[0]][parts[3]] += 1

    # ── Stage 1: Main-effects regression ─────────────────────────────────────
    train_ids = sorted(train_seqs.keys())
    test_ids = sorted(test_seqs.keys())
    n_tf = len(tf_names)

    X_train = np.zeros((len(train_ids), n_tf))
    X_test = np.zeros((len(test_ids), n_tf))
    for i, gid in enumerate(train_ids):
        for j, tf in enumerate(tf_names):
            X_train[i, j] = gene_tf_counts[gid][tf]
    for i, gid in enumerate(test_ids):
        for j, tf in enumerate(tf_names):
            X_test[i, j] = gene_tf_counts[gid][tf]
    y_train = np.array([train_expr[gid] for gid in train_ids])

    model = Ridge(alpha=1.0)
    model.fit(X_train, y_train)
    residuals = y_train - model.predict(X_train)

    train_r2 = 1.0 - np.sum(residuals ** 2) / np.sum((y_train - np.mean(y_train)) ** 2)
    print(f"\nStage 1 - Main effects, Train R²: {train_r2:.4f}")
    for j, tf in enumerate(tf_names):
        print(f"  {tf}: {model.coef_[j]:+.3f}")

    # TF roles and master regulator
    tf_roles = {}
    for j, tf in enumerate(tf_names):
        tf_roles[tf] = "activator" if model.coef_[j] > 0 else "repressor"
    master_idx = np.argmax(np.abs(model.coef_))
    master_regulator = tf_names[master_idx]
    print(f"  Master regulator: {master_regulator}")

    # Predictions from main effects model
    test_pred = model.predict(X_test)

    # ── Stage 2: Interaction discovery from residuals ────────────────────────
    print("\nStage 2 - Interaction discovery:")
    interactions = []
    for j1 in range(n_tf):
        for j2 in range(j1 + 1, n_tf):
            co_bind = np.array([
                1.0 if gene_tf_counts[gid][tf_names[j1]] > 0 and gene_tf_counts[gid][tf_names[j2]] > 0
                else 0.0 for gid in train_ids
            ])
            n_co = int(co_bind.sum())
            if n_co < 10 or co_bind.std() == 0:
                continue
            mean_co = residuals[co_bind > 0].mean()
            mean_not = residuals[co_bind == 0].mean()
            diff = mean_co - mean_not
            corr = np.corrcoef(co_bind, residuals)[0, 1]
            if abs(corr) > 0.08 and abs(diff) > 0.5:
                itype = "cooperative" if diff > 0 else "antagonistic"
                interactions.append({
                    "tf1": tf_names[j1],
                    "tf2": tf_names[j2],
                    "type": itype,
                })
                print(f"  {tf_names[j1]}-{tf_names[j2]}: corr={corr:.3f}, diff={diff:.2f} ({itype})")

    # ── Write outputs ────────────────────────────────────────────────────────
    with open(os.path.join(RESULTS_DIR, "tf_roles.json"), "w") as f:
        json.dump(tf_roles, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "master_regulator.txt"), "w") as f:
        f.write(master_regulator + "\n")

    with open(os.path.join(RESULTS_DIR, "predictions.tsv"), "w") as f:
        f.write("gene_id\tpredicted_expression\n")
        for gid, pred in zip(test_ids, test_pred):
            f.write(f"{gid}\t{pred:.3f}\n")

    with open(os.path.join(RESULTS_DIR, "functional_binding.bed"), "w") as f:
        for line in sorted(functional_lines):
            f.write(line + "\n")

    network = {
        "tf_roles": tf_roles,
        "master_regulator": master_regulator,
        "interactions": interactions,
    }
    with open(os.path.join(RESULTS_DIR, "regulatory_network.json"), "w") as f:
        json.dump(network, f, indent=2)

    print(f"\nOutputs written to {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
