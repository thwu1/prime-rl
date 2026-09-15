#!/usr/bin/env python3
"""Mean-field Direct Coupling Analysis (mfDCA) for protein contact prediction.

Infers residue-residue contacts from multiple sequence alignment data by
estimating the precision matrix of the amino acid frequency distribution.
Exports score matrices for gnuplot visualization and a pipeline report TSV.
"""

import numpy as np
import json
import os
import sys


def parse_fasta(filepath):
    """Parse FASTA file to integer-encoded sequence array."""
    aa_map = {"A": 0, "C": 1, "D": 2, "E": 3, "F": 4}
    sequences = []
    current = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current:
                    sequences.append(current)
                current = []
            else:
                current.extend(aa_map.get(c, 0) for c in line)
        if current:
            sequences.append(current)
    return np.array(sequences, dtype=np.int32)


def onehot_encode(sequences, q=5):
    """One-hot encode sequences: (N, L) -> (N, L*q)."""
    N, L = sequences.shape
    X = np.zeros((N, L * q), dtype=np.float64)
    rows = np.repeat(np.arange(N), L)
    cols = np.tile(np.arange(L), N) * q + sequences.ravel()
    X[rows, cols] = 1.0
    return X


def compute_weights(X, L, threshold=0.8):
    """Phylogenetic reweighting via pairwise sequence identity."""
    sim = (X @ X.T) / L
    counts = (sim >= threshold).sum(axis=1)
    weights = 1.0 / np.maximum(counts, 1).astype(np.float64)
    Neff = weights.sum()
    return weights, Neff


def mfdca(sequences, q=5, pseudocount=0.5, reg=0.01):
    """Run mean-field DCA and return APC-corrected contact scores.

    Returns: (predictions, L, N, Neff, score_matrix)
    """
    N, L = sequences.shape
    Lq = L * q

    print(f"  N={N}, L={L}, Lq={Lq}", flush=True)

    X = onehot_encode(sequences, q)

    print("  Computing sequence weights...", flush=True)
    weights, Neff = compute_weights(X, L, threshold=0.8)
    print(f"  Neff = {Neff:.1f}", flush=True)

    Xw = X * weights[:, None]

    # Single-site frequencies with pseudocount
    fi = Xw.sum(axis=0) / Neff
    fi = (1 - pseudocount) * fi + pseudocount / q
    fi_2d = fi.reshape(L, q)

    # Pairwise frequency matrix with pseudocount
    print("  Computing pairwise frequencies...", flush=True)
    fij = (Xw.T @ X) / Neff
    fij = (1 - pseudocount) * fij + pseudocount / (q * q)

    # Covariance matrix
    print("  Building covariance matrix...", flush=True)
    C = fij - np.outer(fi, fi)

    # Fix diagonal blocks to single-site connected correlations
    for i in range(L):
        for a in range(q):
            for b in range(q):
                ia = i * q + a
                ib = i * q + b
                if a == b:
                    C[ia, ib] = fi_2d[i, a] * (1.0 - fi_2d[i, a])
                else:
                    C[ia, ib] = -fi_2d[i, a] * fi_2d[i, b]

    # Tikhonov regularization
    C += reg * np.eye(Lq)

    # Invert to get coupling parameters
    print("  Inverting covariance matrix...", flush=True)
    try:
        J = np.linalg.inv(C)
    except np.linalg.LinAlgError:
        print("  WARNING: singular matrix, using pseudoinverse", flush=True)
        J = np.linalg.pinv(C)

    # Frobenius norm of inter-position coupling blocks
    print("  Computing Frobenius norms...", flush=True)
    raw_scores = np.zeros((L, L))
    for i in range(L):
        for j in range(i + 1, L):
            if j - i < 5:
                continue
            block = J[i * q:(i + 1) * q, j * q:(j + 1) * q]
            raw_scores[i, j] = np.linalg.norm(block, "fro")

    # Average Product Correction (APC)
    print("  Applying APC correction...", flush=True)
    row_mean = np.zeros(L)
    row_count = np.zeros(L)
    for i in range(L):
        for j in range(L):
            if i != j and abs(i - j) >= 5:
                row_mean[i] += raw_scores[min(i, j), max(i, j)]
                row_count[i] += 1
    row_mean = np.where(row_count > 0, row_mean / row_count, 0.0)

    valid_scores = []
    for i in range(L):
        for j in range(i + 1, L):
            if j - i >= 5 and raw_scores[i, j] > 0:
                valid_scores.append(raw_scores[i, j])
    global_mean = np.mean(valid_scores) if valid_scores else 1.0

    corrected = np.zeros((L, L))
    for i in range(L):
        for j in range(i + 1, L):
            if j - i < 5:
                continue
            corrected[i, j] = raw_scores[i, j] - row_mean[i] * row_mean[j] / (global_mean + 1e-10)

    # Ranked predictions
    preds = []
    for i in range(L):
        for j in range(i + 1, L):
            if j - i >= 5:
                preds.append([int(i), int(j), float(corrected[i, j])])
    preds.sort(key=lambda x: -x[2])

    # Build full symmetric score matrix for visualization
    score_matrix = np.maximum(corrected + corrected.T, 0)

    return preds, L, N, float(Neff), score_matrix


def load_contacts(filepath):
    """Load ground truth contacts from text file."""
    contacts = []
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                contacts.append((int(parts[0]), int(parts[1])))
    return contacts


def precision_at_L(predictions, true_contacts, L):
    """Compute precision@L: fraction of top L predictions that are true."""
    true_set = set(true_contacts)
    true_set_both = true_set | {(j, i) for (i, j) in true_set}
    top_L = predictions[:L]
    tp = sum(1 for p in top_L if (p[0], p[1]) in true_set_both)
    return tp / L if L > 0 else 0.0


def write_score_matrix(score_matrix, filepath):
    """Write score matrix as space-separated values for gnuplot."""
    np.savetxt(filepath, score_matrix, fmt="%.6f", delimiter=" ")


def write_gnuplot_script(family, L, dat_path, png_path, gp_path):
    """Write a gnuplot script for contact map heatmap rendering."""
    script = f"""set terminal pngcairo size 800,800 enhanced font "sans,11"
set output '{png_path}'
set title '{family} - Predicted Contact Map' noenhanced
set xlabel 'Residue Position i'
set ylabel 'Residue Position j'
set xrange [-0.5:{L - 0.5}]
set yrange [-0.5:{L - 0.5}]
set size ratio 1
set palette defined (0 "white", 0.25 "#ffffcc", 0.5 "#fd8d3c", 0.75 "#e31a1c", 1 "#800026")
set cblabel 'DCA Score'
plot '{dat_path}' matrix with image notitle
"""
    with open(gp_path, "w") as f:
        f.write(script)


def write_pipeline_report(results, family_extras, filepath):
    """Write the tab-separated pipeline report."""
    header = "family\tn_sequences\talignment_length\tneff\ttop_score\tprecision_at_L"
    rows = [header]
    for fam in ["family_1", "family_2", "family_3"]:
        r = results[fam]
        ex = family_extras[fam]
        prec_str = f"{r['precision_at_L']:.4f}" if r["precision_at_L"] is not None else "NA"
        row = f"{fam}\t{r['n_sequences']}\t{r['alignment_length']}\t{ex['neff']:.2f}\t{ex['top_score']:.6f}\t{prec_str}"
        rows.append(row)
    with open(filepath, "w") as f:
        f.write("\n".join(rows) + "\n")


def main():
    data_dir = "/data"
    results = {}
    family_extras = {}

    for family in ["family_1", "family_2", "family_3"]:
        fasta_path = os.path.join(data_dir, f"{family}.fasta")
        print(f"\n{'='*50}", flush=True)
        print(f"Processing {family} ({fasta_path})", flush=True)
        print(f"{'='*50}", flush=True)

        if not os.path.exists(fasta_path):
            print(f"  ERROR: {fasta_path} not found", flush=True)
            results[family] = {
                "top_contacts": [],
                "precision_at_L": None,
                "n_sequences": 0,
                "alignment_length": 0,
            }
            family_extras[family] = {"neff": 0.0, "top_score": 0.0}
            continue

        sequences = parse_fasta(fasta_path)
        preds, L, N, Neff, score_matrix = mfdca(sequences, q=5, pseudocount=0.5, reg=0.01)

        top_score = preds[0][2] if preds else 0.0

        # Compute precision for family_1 using provided ground truth
        prec = None
        if family == "family_1":
            contacts_path = os.path.join(data_dir, "family_1_contacts.txt")
            if os.path.exists(contacts_path):
                true_contacts = load_contacts(contacts_path)
                prec = precision_at_L(preds, true_contacts, L)
                print(f"  Precision@L = {prec:.4f}", flush=True)

        results[family] = {
            "top_contacts": preds[:L],
            "precision_at_L": prec,
            "n_sequences": int(N),
            "alignment_length": int(L),
        }
        family_extras[family] = {"neff": Neff, "top_score": top_score}

        # Export score matrix and gnuplot script for heatmap
        dat_path = f"/app/scores_{family}.dat"
        png_path = f"/app/contact_map_{family}.png"
        gp_path = f"/app/plot_{family}.gp"

        print(f"  Writing score matrix to {dat_path}", flush=True)
        write_score_matrix(score_matrix, dat_path)
        write_gnuplot_script(family, L, dat_path, png_path, gp_path)
        print(f"  Wrote gnuplot script to {gp_path}", flush=True)

    # Write results.json
    output_path = "/app/results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {output_path}", flush=True)

    # Write pipeline report TSV
    report_path = "/app/pipeline_report.tsv"
    write_pipeline_report(results, family_extras, report_path)
    print(f"Pipeline report written to {report_path}", flush=True)


if __name__ == "__main__":
    main()
