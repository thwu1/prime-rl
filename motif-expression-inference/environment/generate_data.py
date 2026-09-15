#!/usr/bin/env python3
"""
Generate synthetic regulatory genomics dataset for motif-expression-inference task.
Deterministic with seed=42. Pure Python (no numpy required).
"""
import json
import math
import os
import random
import bisect

random.seed(42)

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASES = "ACGT"
BASE_TO_IDX = {"A": 0, "C": 1, "G": 2, "T": 3}
BG_FREQ = [0.29, 0.21, 0.21, 0.29]

# ── TF definitions ──────────────────────────────────────────────────────────
TF_INFO = {
    "TF_A": {"coeff":  2.5, "role": "activator"},
    "TF_B": {"coeff": -1.8, "role": "repressor"},
    "TF_C": {"coeff":  3.2, "role": "activator"},
    "TF_D": {"coeff": -2.1, "role": "repressor"},
    "TF_E": {"coeff":  1.5, "role": "activator"},
    "TF_F": {"coeff":  2.8, "role": "activator"},
    "TF_G": {"coeff": -1.2, "role": "repressor"},
    "TF_H": {"coeff":  0.9, "role": "activator"},
}
TF_NAMES = sorted(TF_INFO.keys())

# PWMs: each row = [P(A), P(C), P(G), P(T)] at that position.
PWMS = {
    "TF_A": [  # E-box variant, consensus CACGTGACTA (10bp)
        [0.04, 0.88, 0.04, 0.04],
        [0.88, 0.04, 0.04, 0.04],
        [0.07, 0.79, 0.10, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.07, 0.83, 0.06],
        [0.83, 0.06, 0.07, 0.04],
        [0.04, 0.88, 0.04, 0.04],
        [0.07, 0.04, 0.04, 0.85],
        [0.85, 0.04, 0.07, 0.04],
    ],
    "TF_B": [  # GATA-like, consensus AGATAAG (8bp)  -- note: last base is G not T
        [0.87, 0.04, 0.05, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.88, 0.04, 0.04, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.85, 0.05, 0.06, 0.04],
        [0.86, 0.04, 0.04, 0.06],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
    ],
    "TF_C": [  # AP-1 variant, consensus TGACTCAGCA (10bp)
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.88, 0.04],
        [0.88, 0.04, 0.04, 0.04],
        [0.04, 0.82, 0.10, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.86, 0.04, 0.06],
        [0.88, 0.04, 0.04, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.87, 0.05, 0.04],
        [0.85, 0.04, 0.07, 0.04],
    ],
    "TF_D": [  # ETS-like, consensus AGGAAGTTC (9bp)
        [0.86, 0.04, 0.06, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.88, 0.04, 0.04, 0.04],
        [0.85, 0.07, 0.04, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.06, 0.86],
        [0.04, 0.87, 0.05, 0.04],
    ],
    "TF_E": [  # CRE-like, consensus TGACGTCA (8bp)
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.88, 0.04],
        [0.88, 0.04, 0.04, 0.04],
        [0.04, 0.83, 0.04, 0.09],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.86, 0.06, 0.04],
        [0.86, 0.04, 0.06, 0.04],
    ],
    "TF_F": [  # NF-kB-like, consensus GGGACTTTCC (10bp)
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.88, 0.04, 0.04, 0.04],
        [0.04, 0.85, 0.04, 0.07],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.06, 0.86],
        [0.04, 0.87, 0.05, 0.04],
        [0.04, 0.86, 0.04, 0.06],
    ],
    "TF_G": [  # SP1/GC-box-like, consensus GGGCGGAG (8bp)
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.86, 0.06, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.86, 0.04, 0.06, 0.04],
        [0.04, 0.04, 0.88, 0.04],
    ],
    "TF_H": [  # RUNX-like, consensus TGTGGTCAA (9bp)
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.88, 0.04],
        [0.04, 0.04, 0.04, 0.88],
        [0.04, 0.85, 0.07, 0.04],
        [0.86, 0.04, 0.06, 0.04],
        [0.87, 0.04, 0.05, 0.04],
    ],
}

PROMOTER_LEN = 600
N_TRAIN = 150
N_TEST = 50
INTERCEPT = 5.0
NOISE_STD = 0.8
BASE_BIND_PROB = 0.33


def weighted_choice(options, weights):
    """Choose from options with given weights (replacement for np.random.choice)."""
    cumw = []
    total = 0.0
    for w in weights:
        total += w
        cumw.append(total)
    r = random.random() * total
    idx = bisect.bisect_left(cumw, r)
    return options[min(idx, len(options) - 1)]


def gauss(mu, sigma):
    """Box-Muller Gaussian."""
    return random.gauss(mu, sigma)


def reverse_complement(seq):
    comp = {"A": "T", "C": "G", "G": "C", "T": "A", "N": "N"}
    return "".join(comp[b] for b in reversed(seq))


def sample_from_pwm(pwm):
    seq = []
    for pos_probs in pwm:
        base = weighted_choice(list(BASES), pos_probs)
        seq.append(base)
    return "".join(seq)


def generate_background_seq(length):
    return "".join(weighted_choice(list(BASES), BG_FREQ) for _ in range(length))


def embed_sites(bg_seq, sites_to_embed):
    seq = list(bg_seq)
    occupied = set()

    for tf_name, site_seq, on_rc_strand in sites_to_embed:
        motif_len = len(site_seq)
        if on_rc_strand:
            embed_seq = reverse_complement(site_seq)
        else:
            embed_seq = site_seq

        for _ in range(200):
            pos = random.randint(15, len(seq) - motif_len - 15)
            conflict = False
            for p in range(pos - 2, pos + motif_len + 2):
                if p in occupied:
                    conflict = True
                    break
            if not conflict:
                for i, base in enumerate(embed_seq):
                    seq[pos + i] = base
                for p in range(pos, pos + motif_len):
                    occupied.add(p)
                break

    return "".join(seq)


def generate_dataset():
    all_genes = []
    all_binding = []
    all_expressions = []
    all_seqs = []

    for gene_idx in range(N_TRAIN + N_TEST):
        gene_id = f"GENE_{gene_idx + 1:03d}"

        binding = {}
        for tf in TF_NAMES:
            prob = BASE_BIND_PROB

            # Correlation structure
            if tf == "TF_H" and binding.get("TF_E", 0) > 0:
                prob = 0.07
            if tf == "TF_D" and binding.get("TF_B", 0) > 0:
                prob = 0.55

            if random.random() < prob:
                n_sites = weighted_choice([1, 2, 3], [0.55, 0.35, 0.10])
                binding[tf] = n_sites
            else:
                binding[tf] = 0

        # Generate promoter with embedded sites
        bg_seq = generate_background_seq(PROMOTER_LEN)
        sites_to_embed = []
        for tf in TF_NAMES:
            for _ in range(binding[tf]):
                site = sample_from_pwm(PWMS[tf])
                on_rc = random.random() < 0.3
                sites_to_embed.append((tf, site, on_rc))

        random.shuffle(sites_to_embed)
        seq = embed_sites(bg_seq, sites_to_embed)

        # Expression = linear model + noise
        expr = INTERCEPT
        for tf in TF_NAMES:
            expr += TF_INFO[tf]["coeff"] * binding[tf]
        expr += gauss(0, NOISE_STD)
        expr = max(0.1, round(expr, 3))

        all_genes.append(gene_id)
        all_binding.append({tf: binding[tf] for tf in TF_NAMES})
        all_expressions.append(expr)
        all_seqs.append(seq)

    # Split
    train_genes = all_genes[:N_TRAIN]
    test_genes  = all_genes[N_TRAIN:]
    train_expr  = all_expressions[:N_TRAIN]
    test_expr   = all_expressions[N_TRAIN:]
    train_seqs  = all_seqs[:N_TRAIN]
    test_seqs   = all_seqs[N_TRAIN:]

    # ── Write motifs.json ────────────────────────────────────────────────────
    motifs_out = {}
    for tf in TF_NAMES:
        pwm = PWMS[tf]
        consensus = "".join(BASES[max(range(4), key=lambda i: row[i])] for row in pwm)
        motifs_out[tf] = {
            "pwm": pwm,
            "length": len(pwm),
            "consensus": consensus,
        }
    with open(os.path.join(OUTPUT_DIR, "motifs.json"), "w") as f:
        json.dump(motifs_out, f, indent=2)

    # ── Write FASTA files ────────────────────────────────────────────────────
    with open(os.path.join(OUTPUT_DIR, "promoters_train.fasta"), "w") as f:
        for gid, seq in zip(train_genes, train_seqs):
            f.write(f">{gid}\n")
            for i in range(0, len(seq), 80):
                f.write(seq[i:i+80] + "\n")

    with open(os.path.join(OUTPUT_DIR, "promoters_test.fasta"), "w") as f:
        for gid, seq in zip(test_genes, test_seqs):
            f.write(f">{gid}\n")
            for i in range(0, len(seq), 80):
                f.write(seq[i:i+80] + "\n")

    # ── Write expression CSV ─────────────────────────────────────────────────
    with open(os.path.join(OUTPUT_DIR, "expression_train.csv"), "w") as f:
        f.write("gene_id,expression\n")
        for gid, expr in zip(train_genes, train_expr):
            f.write(f"{gid},{expr}\n")

    # ── Write ground truth ───────────────────────────────────────────────────
    ground_truth = {
        "tf_roles": {tf: TF_INFO[tf]["role"] for tf in TF_NAMES},
        "tf_coefficients": {tf: TF_INFO[tf]["coeff"] for tf in TF_NAMES},
        "master_regulator": max(TF_NAMES, key=lambda tf: abs(TF_INFO[tf]["coeff"])),
        "test_expressions": {gid: expr for gid, expr in zip(test_genes, test_expr)},
        "intercept": INTERCEPT,
    }
    with open(os.path.join(OUTPUT_DIR, "ground_truth.json"), "w") as f:
        json.dump(ground_truth, f, indent=2)

    # ── Write README ─────────────────────────────────────────────────────────
    with open(os.path.join(OUTPUT_DIR, "README.txt"), "w") as f:
        f.write(
            "Regulatory Motif-Expression Inference Dataset\n"
            "=============================================\n\n"
            "This dataset contains synthetic promoter sequences with embedded\n"
            "transcription factor (TF) binding sites and corresponding gene\n"
            "expression measurements.\n\n"
            "Files\n"
            "-----\n"
            "- motifs.json: Position Weight Matrices (PWMs) for 8 transcription\n"
            "  factors (TF_A through TF_H). Each entry contains:\n"
            "    - 'pwm': matrix of nucleotide probabilities [P(A), P(C), P(G), P(T)]\n"
            "      at each position\n"
            "    - 'length': motif length in base pairs\n"
            "    - 'consensus': most probable base at each position\n\n"
            "- promoters_train.fasta: 150 promoter sequences (600 bp each) for\n"
            "  model training. Each promoter may contain zero or more TF binding\n"
            "  sites on either DNA strand.\n\n"
            "- promoters_test.fasta: 50 promoter sequences for expression prediction.\n\n"
            "- expression_train.csv: Measured expression levels for the 150 training\n"
            "  genes. Expression is a function of TF binding site composition.\n\n"
            "Model\n"
            "-----\n"
            "Gene expression follows a linear model:\n\n"
            "  expression_g = intercept + sum_i(beta_i * n_sites_i(g)) + noise\n\n"
            "where n_sites_i(g) is the number of binding sites for TF_i found in\n"
            "gene g's promoter, and beta_i is the regulatory coefficient. Positive\n"
            "beta indicates an activator; negative beta indicates a repressor.\n\n"
            "Binding sites may appear on either the forward or reverse strand and\n"
            "should be detected using PWM log-odds scoring against a genomic\n"
            "background model.\n"
        )

    print(f"Generated {N_TRAIN} training + {N_TEST} test genes")
    print(f"Master regulator: {ground_truth['master_regulator']}")
    for tf in TF_NAMES:
        role = TF_INFO[tf]["role"]
        coeff = TF_INFO[tf]["coeff"]
        print(f"  {tf}: {role} (coeff={coeff:+.1f})")
    return ground_truth


if __name__ == "__main__":
    gt = generate_dataset()
