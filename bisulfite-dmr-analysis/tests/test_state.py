
"""Tests for differentially methylated region analysis."""

import random
import os
import csv
import math
import pytest


def read_tsv(path):
    """Read a TSV file and return list of dicts."""
    with open(path) as f:
        reader = csv.DictReader(f, delimiter='\t')
        return list(reader)


def _regenerate_truth():
    """Regenerate structural truth using the same deterministic seed as data generation.

    This replays the structural RNG (seed=20260612) to recover CpG positions,
    planted effects, DMC assignments, and DMR cluster definitions without
    needing any truth files on disk.
    """
    rng = random.Random(20260612)

    N_CPGS = 500
    N_DMR_CLUSTERS = 5
    N_TOTAL_DMCS = 40

    cluster_spacing = 44_000_000 // (N_DMR_CLUSTERS + 1)
    cluster_centers = [3_000_000 + (i + 1) * cluster_spacing
                       for i in range(N_DMR_CLUSTERS)]

    cluster_positions_list = []
    all_cluster_pos = []

    for center in cluster_centers:
        size = rng.randint(3, 5)
        cluster = []
        pos = center
        for j in range(size):
            cluster.append(pos)
            pos += rng.randint(150, 300)
        cluster_positions_list.append(sorted(cluster))
        all_cluster_pos.extend(cluster)

    all_cluster_pos_set = set(all_cluster_pos)

    scattered = []
    scattered_set = set()
    attempts = 0
    n_needed = N_CPGS - len(all_cluster_pos)
    while len(scattered) < n_needed and attempts < 500000:
        p = rng.randint(1_000_000, 50_000_000)
        if (p not in all_cluster_pos_set and p not in scattered_set
                and all(abs(p - c) > 5000 for c in cluster_centers)):
            scattered.append(p)
            scattered_set.add(p)
        attempts += 1

    all_pos = sorted(all_cluster_pos + scattered[:n_needed])
    while len(all_pos) < N_CPGS:
        p = rng.randint(1_000_000, 50_000_000)
        if p not in set(all_pos):
            all_pos.append(p)
    all_pos = sorted(set(all_pos))[:N_CPGS]
    positions = all_pos

    cpg_ids = [f"cpg_{i+1:04d}" for i in range(N_CPGS)]

    pos_to_idx = {p: i for i, p in enumerate(positions)}
    dmr_cluster_indices = []
    for cluster_pos in cluster_positions_list:
        indices = [pos_to_idx[cp] for cp in cluster_pos if cp in pos_to_idx]
        if len(indices) >= 3:
            dmr_cluster_indices.append(indices)

    dmr_cpg_set = set()
    for cluster in dmr_cluster_indices:
        dmr_cpg_set.update(cluster)

    n_individual = N_TOTAL_DMCS - len(dmr_cpg_set)
    available = [i for i in range(N_CPGS) if i not in dmr_cpg_set]
    individual_dmc_indices = sorted(
        rng.sample(available, min(n_individual, len(available))))

    all_dmc_set = dmr_cpg_set | set(individual_dmc_indices)

    effects = [0.0] * N_CPGS
    for cluster in dmr_cluster_indices:
        direction = rng.choice([-1, 1])
        for idx in cluster:
            effects[idx] = direction * rng.uniform(0.18, 0.40)

    for idx in individual_dmc_indices:
        d = rng.choice([-1, 1])
        effects[idx] = d * rng.uniform(0.18, 0.40)

    truth_dmrs = []
    for cluster in dmr_cluster_indices:
        start = positions[cluster[0]]
        end = positions[cluster[-1]]
        mean_eff = sum(effects[idx] for idx in cluster) / len(cluster)
        truth_dmrs.append({
            'start': start, 'end': end, 'mean_effect': mean_eff
        })

    return {
        'cpg_ids': cpg_ids,
        'positions': positions,
        'effects': effects,
        'all_dmc_set': all_dmc_set,
        'truth_dmrs': truth_dmrs,
    }


_TRUTH_CACHE = None


def get_truth():
    """Return cached truth data (computed once per test session)."""
    global _TRUTH_CACHE
    if _TRUTH_CACHE is None:
        _TRUTH_CACHE = _regenerate_truth()
    return _TRUTH_CACHE


def spearman_correlation(x, y):
    """Compute Spearman rank correlation coefficient."""
    n = len(x)
    if n < 3:
        return 0.0

    def rank(vals):
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            mean_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = mean_rank
            i = j + 1
        return ranks

    rx = rank(x)
    ry = rank(y)

    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n

    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))

    if den_x == 0 or den_y == 0:
        return 0.0

    return num / (den_x * den_y)


def f1_score(predicted_set, truth_set):
    """Compute F1 score between two sets."""
    if not predicted_set and not truth_set:
        return 1.0
    if not predicted_set or not truth_set:
        return 0.0

    tp = len(predicted_set & truth_set)
    precision = tp / len(predicted_set) if predicted_set else 0
    recall = tp / len(truth_set) if truth_set else 0

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


class TestCpgResults:
    """Test CpG-level differential methylation results."""

    def test_cpg_file_exists(self):
        assert os.path.exists('/app/cpg_results.tsv'), \
            "cpg_results.tsv not found in /app/"

    def test_cpg_columns(self):
        rows = read_tsv('/app/cpg_results.tsv')
        assert len(rows) > 0, "cpg_results.tsv is empty"
        required = {'cpg_id', 'chr', 'position', 'mean_case_beta',
                     'mean_ctrl_beta', 'delta_beta', 'pvalue', 'padj',
                     'significant'}
        actual = set(rows[0].keys())
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_cpg_count_reasonable(self):
        """After filtering low-coverage CpGs, expect ~400-500 tested CpGs."""
        rows = read_tsv('/app/cpg_results.tsv')
        n = len(rows)
        assert 350 <= n <= 500, f"Expected 350-500 tested CpGs, got {n}"

    def test_delta_beta_correlation(self):
        """Delta-beta values should correlate with true effects."""
        truth = get_truth()
        truth_map = {truth['cpg_ids'][i]: truth['effects'][i]
                     for i in range(len(truth['cpg_ids']))}

        results = read_tsv('/app/cpg_results.tsv')

        paired_truth = []
        paired_pred = []
        for r in results:
            cpg_id = r['cpg_id']
            if cpg_id in truth_map:
                paired_truth.append(truth_map[cpg_id])
                paired_pred.append(float(r['delta_beta']))

        assert len(paired_truth) >= 100, \
            f"Too few matched CpGs: {len(paired_truth)}"

        rho = spearman_correlation(paired_truth, paired_pred)
        assert rho > 0.4, \
            f"Spearman correlation of delta_beta = {rho:.3f}, expected > 0.4"

    def test_significant_cpgs_f1(self):
        """F1 score for significant CpGs vs planted DMCs."""
        truth = get_truth()
        truth_dmcs = {truth['cpg_ids'][i] for i in truth['all_dmc_set']}

        results = read_tsv('/app/cpg_results.tsv')
        pred_sig = {r['cpg_id'] for r in results
                    if r['significant'].strip().upper() == 'TRUE'}

        f1 = f1_score(pred_sig, truth_dmcs)
        assert f1 > 0.3, \
            f"F1 score for significant CpGs = {f1:.3f}, expected > 0.3"

    def test_significant_count_range(self):
        """Number of significant CpGs should be in reasonable range."""
        results = read_tsv('/app/cpg_results.tsv')
        n_sig = sum(1 for r in results
                    if r['significant'].strip().upper() == 'TRUE')
        assert 15 <= n_sig <= 60, \
            f"Expected 15-60 significant CpGs, got {n_sig}"

    def test_beta_values_valid(self):
        """Beta values should be in [0, 1]."""
        results = read_tsv('/app/cpg_results.tsv')
        for r in results[:50]:
            case_b = float(r['mean_case_beta'])
            ctrl_b = float(r['mean_ctrl_beta'])
            assert 0 <= case_b <= 1, f"Invalid case beta: {case_b}"
            assert 0 <= ctrl_b <= 1, f"Invalid ctrl beta: {ctrl_b}"

    def test_pvalues_valid(self):
        """P-values should be in [0, 1]."""
        results = read_tsv('/app/cpg_results.tsv')
        for r in results:
            pval = float(r['pvalue'])
            padj = float(r['padj'])
            assert 0 <= pval <= 1, f"Invalid p-value: {pval}"
            assert 0 <= padj <= 1, f"Invalid adjusted p-value: {padj}"


class TestDmrResults:
    """Test differentially methylated region results."""

    def test_dmr_file_exists(self):
        assert os.path.exists('/app/dmr_results.tsv'), \
            "dmr_results.tsv not found in /app/"

    def test_dmr_columns(self):
        rows = read_tsv('/app/dmr_results.tsv')
        assert len(rows) > 0, "dmr_results.tsv is empty"
        required = {'dmr_id', 'chr', 'start', 'end', 'n_cpgs',
                     'mean_delta_beta', 'direction', 'nearest_gene',
                     'distance_to_tss'}
        actual = set(rows[0].keys())
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_dmr_count_range(self):
        """Number of DMRs should be in reasonable range."""
        rows = read_tsv('/app/dmr_results.tsv')
        n = len(rows)
        assert 3 <= n <= 15, f"Expected 3-15 DMRs, got {n}"

    def test_dmr_overlap_with_truth(self):
        """Predicted DMRs should overlap with planted truth DMRs."""
        truth = get_truth()
        truth_dmrs = truth['truth_dmrs']
        pred_dmrs = read_tsv('/app/dmr_results.tsv')

        def intervals_overlap(s1, e1, s2, e2, slop=500):
            return (s1 - slop) <= e2 and (s2 - slop) <= e1

        truth_recovered = 0
        for td in truth_dmrs:
            t_start = td['start']
            t_end = td['end']
            for pd in pred_dmrs:
                p_start = int(pd['start'])
                p_end = int(pd['end'])
                if intervals_overlap(t_start, t_end, p_start, p_end):
                    truth_recovered += 1
                    break

        n_truth = len(truth_dmrs)
        recovery = truth_recovered / n_truth if n_truth > 0 else 0
        assert recovery >= 0.4, \
            f"DMR recovery = {recovery:.2f} ({truth_recovered}/{n_truth}), expected >= 0.4"

    def test_dmr_direction_consistency(self):
        """DMR direction label should match sign of mean_delta_beta."""
        rows = read_tsv('/app/dmr_results.tsv')
        for r in rows:
            delta = float(r['mean_delta_beta'])
            direction = r['direction'].strip().lower()
            if delta > 0:
                assert direction == 'hyper', \
                    f"DMR {r['dmr_id']}: delta={delta} but direction={direction}"
            elif delta < 0:
                assert direction == 'hypo', \
                    f"DMR {r['dmr_id']}: delta={delta} but direction={direction}"

    def test_dmr_min_cpgs(self):
        """Each DMR should have at least 3 CpGs."""
        rows = read_tsv('/app/dmr_results.tsv')
        for r in rows:
            n_cpgs = int(r['n_cpgs'])
            assert n_cpgs >= 3, \
                f"DMR {r['dmr_id']} has only {n_cpgs} CpGs, need >= 3"

    def test_nearest_gene_valid(self):
        """DMRs should be annotated with genes from the provided gene set."""
        rows = read_tsv('/app/dmr_results.tsv')
        genes = read_tsv('/opt/data/gene_annotations.tsv')
        valid_genes = {g['gene_id'] for g in genes}

        for r in rows:
            gene = r['nearest_gene'].strip()
            assert gene in valid_genes, \
                f"DMR {r['dmr_id']} annotated with unknown gene '{gene}'"

    def test_distance_to_tss_reasonable(self):
        """Distance to TSS should be non-negative and approximately correct."""
        rows = read_tsv('/app/dmr_results.tsv')
        genes = read_tsv('/opt/data/gene_annotations.tsv')
        gene_tss = {g['gene_id']: int(g['tss']) for g in genes}

        for r in rows:
            dist = int(r['distance_to_tss'])
            assert dist >= 0, \
                f"DMR {r['dmr_id']} has negative distance: {dist}"

            gene = r['nearest_gene'].strip()
            if gene in gene_tss:
                dmr_center = (int(r['start']) + int(r['end'])) // 2
                expected_dist = abs(dmr_center - gene_tss[gene])
                assert abs(dist - expected_dist) <= 1000, \
                    f"DMR {r['dmr_id']}: distance={dist}, expected ~{expected_dist}"


class TestQcReport:
    """Test quality control report."""

    def test_qc_file_exists(self):
        assert os.path.exists('/app/qc_report.tsv'), \
            "qc_report.tsv not found in /app/"

    def test_qc_columns(self):
        rows = read_tsv('/app/qc_report.tsv')
        assert len(rows) > 0, "qc_report.tsv is empty"
        required = {'metric', 'value'}
        actual = set(rows[0].keys())
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_qc_required_metrics(self):
        """QC report should contain all required metrics."""
        rows = read_tsv('/app/qc_report.tsv')
        metrics = {r['metric'] for r in rows}
        required = {'total_cpgs', 'filtered_cpgs', 'tested_cpgs',
                     'significant_cpgs', 'n_dmrs', 'batch_correction_method'}
        missing = required - metrics
        assert not missing, f"Missing QC metrics: {missing}"

    def test_qc_total_cpgs(self):
        """Total CpGs should be 500."""
        rows = read_tsv('/app/qc_report.tsv')
        metrics = {r['metric']: r['value'] for r in rows}
        total = int(metrics.get('total_cpgs', 0))
        assert total == 500, f"Expected total_cpgs=500, got {total}"

    def test_batch_correction_applied(self):
        """Batch correction method should be specified."""
        rows = read_tsv('/app/qc_report.tsv')
        metrics = {r['metric']: r['value'] for r in rows}
        method = metrics.get('batch_correction_method', '').strip()
        assert method and method.lower() != 'none', \
            "Batch correction should be applied"
