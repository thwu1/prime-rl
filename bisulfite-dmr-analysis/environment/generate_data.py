#!/usr/bin/env python3
"""Generate synthetic bisulfite sequencing data with batch confound and planted DMCs/DMRs.

"""

import random
import math
import os
import sys


def poisson_sample(rng, lam):
    """Sample from Poisson distribution using stdlib only."""
    if lam <= 0:
        return 0
    if lam < 30:
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= rng.random()
        return k - 1
    else:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def binomial_sample(rng, n, p):
    """Sample from Binomial(n, p) using stdlib only."""
    if n <= 0:
        return 0
    p = max(0.0, min(1.0, p))
    count = 0
    for _ in range(n):
        if rng.random() < p:
            count += 1
    return count


def main():
    # Structural RNG: determines positions, effects, DMC/DMR assignments
    struct_rng = random.Random(20260612)

    N_CPGS = 500
    N_CASE = 8
    N_CTRL = 8
    N_SAMPLES = N_CASE + N_CTRL
    N_DMR_CLUSTERS = 5
    N_TOTAL_DMCS = 40

    case_names = [f"case_{i+1}" for i in range(N_CASE)]
    ctrl_names = [f"ctrl_{i+1}" for i in range(N_CTRL)]
    sample_names = case_names + ctrl_names

    # UNBALANCED batch assignment: batch is confounded with condition
    # Case: 6 batch A, 2 batch B; Control: 2 batch A, 6 batch B
    batches = ['A', 'A', 'A', 'A', 'A', 'A', 'B', 'B',
               'A', 'A', 'B', 'B', 'B', 'B', 'B', 'B']
    sexes = ['M', 'F', 'M', 'F', 'M', 'F', 'M', 'F',
             'M', 'F', 'M', 'F', 'M', 'F', 'M', 'F']

    # === Generate CpG positions with embedded tight clusters for DMR planting ===
    cluster_spacing = 44_000_000 // (N_DMR_CLUSTERS + 1)
    cluster_centers = [3_000_000 + (i + 1) * cluster_spacing for i in range(N_DMR_CLUSTERS)]

    cluster_positions_list = []
    all_cluster_pos = []

    for center in cluster_centers:
        size = struct_rng.randint(3, 5)
        cluster = []
        pos = center
        for j in range(size):
            cluster.append(pos)
            pos += struct_rng.randint(150, 300)
        cluster_positions_list.append(sorted(cluster))
        all_cluster_pos.extend(cluster)

    all_cluster_pos_set = set(all_cluster_pos)

    # Generate scattered CpGs avoiding cluster neighborhoods
    scattered = []
    scattered_set = set()
    attempts = 0
    n_needed = N_CPGS - len(all_cluster_pos)
    while len(scattered) < n_needed and attempts < 500000:
        p = struct_rng.randint(1_000_000, 50_000_000)
        if (p not in all_cluster_pos_set and p not in scattered_set
                and all(abs(p - c) > 5000 for c in cluster_centers)):
            scattered.append(p)
            scattered_set.add(p)
        attempts += 1

    all_pos = sorted(all_cluster_pos + scattered[:n_needed])
    while len(all_pos) < N_CPGS:
        p = struct_rng.randint(1_000_000, 50_000_000)
        if p not in set(all_pos):
            all_pos.append(p)
    all_pos = sorted(set(all_pos))[:N_CPGS]
    positions = all_pos

    if len(positions) != N_CPGS:
        print(f"ERROR: Expected {N_CPGS} positions, got {len(positions)}", file=sys.stderr)
        sys.exit(1)

    cpg_ids = [f"cpg_{i+1:04d}" for i in range(N_CPGS)]

    # Find cluster indices in sorted positions
    pos_to_idx = {p: i for i, p in enumerate(positions)}
    dmr_cluster_indices = []
    for cluster_pos in cluster_positions_list:
        indices = []
        for cp in cluster_pos:
            if cp in pos_to_idx:
                indices.append(pos_to_idx[cp])
        if len(indices) >= 3:
            dmr_cluster_indices.append(indices)

    dmr_cpg_set = set()
    for cluster in dmr_cluster_indices:
        dmr_cpg_set.update(cluster)

    # Select additional individual DMCs (not in DMR clusters)
    n_individual = N_TOTAL_DMCS - len(dmr_cpg_set)
    available = [i for i in range(N_CPGS) if i not in dmr_cpg_set]
    individual_dmc_indices = sorted(struct_rng.sample(available, min(n_individual, len(available))))

    all_dmc_set = dmr_cpg_set | set(individual_dmc_indices)

    # === Assign effects ===
    effects = [0.0] * N_CPGS

    # DMR cluster effects: consistent direction within each cluster
    for cluster in dmr_cluster_indices:
        direction = struct_rng.choice([-1, 1])
        for idx in cluster:
            effects[idx] = direction * struct_rng.uniform(0.18, 0.40)

    # Individual DMC effects
    for idx in individual_dmc_indices:
        d = struct_rng.choice([-1, 1])
        effects[idx] = d * struct_rng.uniform(0.18, 0.40)

    # === Count data RNG (separate from structural RNG) ===
    data_rng = random.Random(98765)

    # Base methylation levels
    base_beta = [data_rng.betavariate(2, 5) for _ in range(N_CPGS)]

    # Per-CpG batch effects (strong enough to confound without correction)
    batch_effects = [data_rng.gauss(0, 0.12) for _ in range(N_CPGS)]

    # Determine low-coverage CpGs (avoid DMCs)
    non_dmc = [i for i in range(N_CPGS) if i not in all_dmc_set]
    n_low_cov = 40
    low_cov_set = set(data_rng.sample(non_dmc, min(n_low_cov, len(non_dmc))))

    # === Generate observations ===
    totals = [[0] * N_SAMPLES for _ in range(N_CPGS)]
    meths = [[0] * N_SAMPLES for _ in range(N_CPGS)]

    for i in range(N_CPGS):
        for j in range(N_SAMPLES):
            is_case = j < N_CASE
            is_batch_b = (batches[j] == 'B')

            mu = base_beta[i]
            if is_case:
                mu += effects[i]
            if is_batch_b:
                mu += batch_effects[i]
            mu += data_rng.gauss(0, 0.03)
            mu = max(0.01, min(0.99, mu))

            if i in low_cov_set:
                total = max(1, poisson_sample(data_rng, 5))
            else:
                total = max(1, poisson_sample(data_rng, 50))

            totals[i][j] = total
            meths[i][j] = binomial_sample(data_rng, total, mu)

    # === Write input files to /opt/data/ (NO truth files) ===
    os.makedirs('/opt/data', exist_ok=True)

    with open('/opt/data/bisulfite_counts.tsv', 'w') as f:
        header = ['cpg_id', 'chr', 'position']
        for s in sample_names:
            header.extend([f'{s}_meth', f'{s}_total'])
        f.write('\t'.join(header) + '\n')
        for i in range(N_CPGS):
            row = [cpg_ids[i], 'chr1', str(positions[i])]
            for j in range(N_SAMPLES):
                row.extend([str(meths[i][j]), str(totals[i][j])])
            f.write('\t'.join(row) + '\n')

    with open('/opt/data/sample_metadata.tsv', 'w') as f:
        f.write('sample_id\tcondition\tbatch\tsex\n')
        for j in range(N_SAMPLES):
            cond = 'case' if j < N_CASE else 'control'
            f.write(f'{sample_names[j]}\t{cond}\t{batches[j]}\t{sexes[j]}\n')

    # Gene annotations (50 genes on chr1) — separate RNG
    gene_rng = random.Random(77777)
    n_genes = 50
    gene_tss = sorted(gene_rng.sample(range(1_000_000, 50_000_000), n_genes))
    gene_ids = [f'GENE_{g+1:03d}' for g in range(n_genes)]
    gene_strands = [gene_rng.choice(['+', '-']) for _ in range(n_genes)]

    with open('/opt/data/gene_annotations.tsv', 'w') as f:
        f.write('gene_id\tchr\ttss\tstrand\n')
        for g in range(n_genes):
            f.write(f'{gene_ids[g]}\tchr1\t{gene_tss[g]}\t{gene_strands[g]}\n')

    # === Verification ===
    for fpath in ['/opt/data/bisulfite_counts.tsv', '/opt/data/sample_metadata.tsv',
                  '/opt/data/gene_annotations.tsv']:
        if not os.path.exists(fpath):
            print(f"ERROR: {fpath} was not created!", file=sys.stderr)
            sys.exit(1)
        size = os.path.getsize(fpath)
        if size == 0:
            print(f"ERROR: {fpath} is empty!", file=sys.stderr)
            sys.exit(1)

    print(f"Generated: {N_CPGS} CpGs, {len(all_dmc_set)} DMCs, {len(dmr_cluster_indices)} DMRs")
    print(f"DMR sizes: {[len(c) for c in dmr_cluster_indices]}")
    print(f"Low-coverage CpGs: {len(low_cov_set)}")
    print("All input files verified.")


if __name__ == '__main__':
    main()
