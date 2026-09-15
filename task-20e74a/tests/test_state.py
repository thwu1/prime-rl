#!/usr/bin/env python3
"""Tests for phylogenetic tree evaluation and community analysis outputs.

Independently recomputes all expected values from raw data and compares
against agent output files in /app/results/.
"""

import os
import re
import warnings

import numpy as np
import pandas as pd
import pytest
from skbio import TreeNode, DistanceMatrix
from skbio.tree import upgma, nj, bme, rf_dists
from skbio.diversity import beta_diversity
from skbio.stats.distance import permanova


_CACHE = {}


def _fix_negative_lengths(tree):
    """Set negative branch lengths to zero."""
    for node in tree.traverse():
        if node.length is not None and node.length < 0:
            node.length = 0.0
    return tree


def _compute_r2(res):
    """Derive R² from PERMANOVA pseudo-F."""
    f_stat = float(res['test statistic'])
    n = int(res['sample size'])
    g = int(res['number of groups'])
    return 1.0 / (1.0 + (n - g) / ((g - 1) * f_stat))


def _get_expected():
    """Compute all expected results from raw data (cached)."""
    if 'expected' in _CACHE:
        return _CACHE['expected']

    # --- Read data ---
    dm_df = pd.read_csv('/app/data/distance_matrix.tsv', sep='\t', index_col=0)
    otu_df = pd.read_csv('/app/data/otu_table.tsv', sep='\t', index_col=0)
    meta = pd.read_csv('/app/data/metadata.tsv', sep='\t', index_col=0)
    ref_tree = TreeNode.read('/app/data/reference_tree.nwk')

    # --- Reconcile OTU names ---
    dm_otus = set(dm_df.index)
    name_map = {}
    for col in otu_df.columns:
        m = re.match(r'OTU_(\d+)', col)
        if m:
            dm_name = f'otu{int(m.group(1)):03d}'
            if dm_name in dm_otus:
                name_map[col] = dm_name

    shared = sorted(name_map.values())
    dm_sub = DistanceMatrix(dm_df.loc[shared, shared].values, ids=shared)
    dm_sub_df = dm_df.loc[shared, shared]
    otu_renamed = otu_df.rename(columns=name_map)[shared]

    # --- Build trees ---
    tree_upgma = _fix_negative_lengths(upgma(dm_sub))
    tree_nj = _fix_negative_lengths(nj(dm_sub)).root_at_midpoint()
    tree_bme = _fix_negative_lengths(bme(dm_sub)).root_at_midpoint()

    tree_tips = {tip.name for tip in ref_tree.tips()}
    ref_pruned = _fix_negative_lengths(
        ref_tree.shear([s for s in shared if s in tree_tips])
    )

    labels = ['reference', 'upgma', 'nj', 'bme']
    trees = [ref_pruned, tree_upgma, tree_nj, tree_bme]

    # --- RF distances ---
    rf = rf_dists(trees)
    rf_df = pd.DataFrame(rf.data, index=labels, columns=labels)

    # --- Cophenetic correlations ---
    coph_results = {}
    for label, tree in zip(labels, trees):
        coph = tree.cophenet()
        coph_inner = coph.to_data_frame()
        common = sorted(set(coph_inner.index) & set(shared))
        n = len(common)
        idx = np.triu_indices(n, k=1)
        c_vals = coph_inner.loc[common, common].values[idx]
        d_vals = dm_sub_df.loc[common, common].values[idx]
        r = float(np.corrcoef(c_vals, d_vals)[0, 1])
        coph_results[label] = r

    best_method = max(coph_results, key=coph_results.get)

    # --- QC ---
    depths = otu_renamed.sum(axis=1)
    passing = sorted([s for s in otu_renamed.index if depths[s] >= 1000])
    failing = sorted([s for s in otu_renamed.index if depths[s] < 1000])
    min_depth = int(depths[passing].min())

    # --- Rarefaction ---
    otu_pass = otu_renamed.loc[passing]
    rng = np.random.default_rng(42)
    rarefied = np.zeros((len(passing), len(shared)), dtype=int)
    for i in range(len(passing)):
        counts = otu_pass.values[i]
        probs = counts / counts.sum()
        rarefied[i] = rng.multinomial(min_depth, probs)

    # --- Metric impact ---
    meta_pass = meta.loc[passing]
    best_tree = trees[labels.index(best_method)]
    impact = {}
    for label, tree in zip(labels, trees):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wuf = beta_diversity('weighted_unifrac', rarefied,
                                 ids=passing, tree=tree, taxa=shared)
        res = permanova(wuf, meta_pass['treatment'], permutations=999, seed=42)
        f_stat = float(res['test statistic'])
        r2 = _compute_r2(res)
        impact[label] = {'pseudo_f': f_stat, 'r_squared': r2}

    # --- Variance partitioning ---
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        best_wuf = beta_diversity('weighted_unifrac', rarefied,
                                  ids=passing, tree=best_tree, taxa=shared)

    res_t = permanova(best_wuf, meta_pass['treatment'], permutations=999, seed=42)
    r2_t = _compute_r2(res_t)

    res_b = permanova(best_wuf, meta_pass['batch'], permutations=999, seed=42)
    r2_b = _compute_r2(res_b)

    combined = meta_pass['treatment'] + '_' + meta_pass['batch']
    combined.name = 'group'
    res_c = permanova(best_wuf, combined, permutations=999, seed=42)
    r2_c = _compute_r2(res_c)

    unique_t = r2_c - r2_b
    unique_b = r2_c - r2_t
    shared_var = r2_t + r2_b - r2_c
    residual = 1.0 - r2_c
    assessment = 'genuine' if unique_t > unique_b else 'confounded'

    expected = {
        'rf_df': rf_df,
        'coph_results': coph_results,
        'best_method': best_method,
        'passing': passing,
        'failing': failing,
        'depths': depths,
        'min_depth': min_depth,
        'impact': impact,
        'labels': labels,
        'vp': {
            'treatment_total': r2_t,
            'batch_total': r2_b,
            'treatment_unique': unique_t,
            'batch_unique': unique_b,
            'shared': shared_var,
            'residual': residual,
        },
        'assessment': assessment,
        'shared': shared,
    }
    _CACHE['expected'] = expected
    return expected


# ===================================================================
# Tests
# ===================================================================


class TestOutputFilesExist:
    @pytest.mark.parametrize("fname", [
        "tree_rf_distances.tsv",
        "cophenetic_correlations.tsv",
        "best_tree_method.txt",
        "best_tree.nwk",
        "sample_qc.tsv",
        "rarefaction_depth.txt",
        "metric_impact.tsv",
        "variance_partitioning.tsv",
        "assessment.txt",
    ])
    def test_file_exists(self, fname):
        assert os.path.exists(f'/app/results/{fname}'), f"Missing output: {fname}"


class TestRFDistances:
    def test_shape(self):
        actual = pd.read_csv('/app/results/tree_rf_distances.tsv',
                             sep='\t', index_col=0)
        assert actual.shape == (4, 4), f"Expected 4x4, got {actual.shape}"

    def test_symmetric(self):
        actual = pd.read_csv('/app/results/tree_rf_distances.tsv',
                             sep='\t', index_col=0)
        np.testing.assert_allclose(
            actual.values, actual.values.T, atol=1e-10,
            err_msg="RF distance matrix is not symmetric")

    def test_labels(self):
        actual = pd.read_csv('/app/results/tree_rf_distances.tsv',
                             sep='\t', index_col=0)
        expected_labels = {'reference', 'upgma', 'nj', 'bme'}
        assert set(actual.index) == expected_labels, \
            f"Row labels: {set(actual.index)}"
        assert set(actual.columns) == expected_labels, \
            f"Col labels: {set(actual.columns)}"

    def test_values(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/tree_rf_distances.tsv',
                             sep='\t', index_col=0)
        order = ['reference', 'upgma', 'nj', 'bme']
        actual = actual.loc[order, order]
        expected = exp['rf_df'].loc[order, order]
        np.testing.assert_allclose(
            actual.values, expected.values, atol=1.0,
            err_msg="RF distances don't match expected")

    def test_zero_diagonal(self):
        actual = pd.read_csv('/app/results/tree_rf_distances.tsv',
                             sep='\t', index_col=0)
        np.testing.assert_allclose(
            np.diag(actual.values), 0.0, atol=1e-10,
            err_msg="RF diagonal should be zero")


class TestCopheneticCorrelations:
    def test_columns(self):
        actual = pd.read_csv('/app/results/cophenetic_correlations.tsv', sep='\t')
        assert 'method' in actual.columns, "Missing 'method' column"
        assert 'pearson_r' in actual.columns, "Missing 'pearson_r' column"

    def test_all_methods(self):
        actual = pd.read_csv('/app/results/cophenetic_correlations.tsv', sep='\t')
        assert set(actual['method']) == {'reference', 'upgma', 'nj', 'bme'}

    def test_sorted_descending(self):
        actual = pd.read_csv('/app/results/cophenetic_correlations.tsv', sep='\t')
        vals = actual['pearson_r'].values
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1] - 1e-9, \
                "Cophenetic correlations not sorted descending"

    def test_values(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/cophenetic_correlations.tsv', sep='\t')
        actual = actual.set_index('method')
        for method, expected_r in exp['coph_results'].items():
            np.testing.assert_allclose(
                float(actual.loc[method, 'pearson_r']), expected_r,
                atol=0.01, err_msg=f"Cophenetic r mismatch for {method}")


class TestBestTreeMethod:
    def test_correct(self):
        exp = _get_expected()
        with open('/app/results/best_tree_method.txt') as f:
            actual = f.read().strip()
        assert actual == exp['best_method'], \
            f"Expected '{exp['best_method']}', got '{actual}'"


class TestBestTreeNewick:
    def test_valid_newick(self):
        tree = TreeNode.read('/app/results/best_tree.nwk')
        assert tree is not None, "Could not parse best_tree.nwk"

    def test_correct_tips(self):
        exp = _get_expected()
        tree = TreeNode.read('/app/results/best_tree.nwk')
        tips = sorted(tip.name for tip in tree.tips())
        assert tips == exp['shared'], \
            f"Expected {len(exp['shared'])} tips, got {len(tips)}"

    def test_has_branch_lengths(self):
        tree = TreeNode.read('/app/results/best_tree.nwk')
        for tip in tree.tips():
            assert tip.length is not None, f"Tip {tip.name} missing branch length"


class TestSampleQC:
    def test_columns(self):
        actual = pd.read_csv('/app/results/sample_qc.tsv', sep='\t')
        required = {'sample_id', 'depth', 'status'}
        assert required.issubset(set(actual.columns)), \
            f"Missing columns: {required - set(actual.columns)}"

    def test_row_count(self):
        actual = pd.read_csv('/app/results/sample_qc.tsv', sep='\t')
        assert len(actual) == 24, f"Expected 24 rows, got {len(actual)}"

    def test_correct_exclusions(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/sample_qc.tsv', sep='\t')
        actual_fail = sorted(
            actual[actual['status'] == 'fail']['sample_id'].tolist())
        assert actual_fail == exp['failing'], \
            f"Expected failures {exp['failing']}, got {actual_fail}"

    def test_correct_passes(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/sample_qc.tsv', sep='\t')
        actual_pass = sorted(
            actual[actual['status'] == 'pass']['sample_id'].tolist())
        assert actual_pass == exp['passing']

    def test_depths(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/sample_qc.tsv', sep='\t')
        actual = actual.set_index('sample_id')
        for sid in exp['passing'] + exp['failing']:
            assert int(actual.loc[sid, 'depth']) == int(exp['depths'][sid]), \
                f"Depth mismatch for {sid}"


class TestRarefactionDepth:
    def test_correct(self):
        exp = _get_expected()
        with open('/app/results/rarefaction_depth.txt') as f:
            actual = int(f.read().strip())
        assert actual == exp['min_depth'], \
            f"Expected {exp['min_depth']}, got {actual}"


class TestMetricImpact:
    def test_columns(self):
        actual = pd.read_csv('/app/results/metric_impact.tsv', sep='\t')
        required = {'tree_method', 'pseudo_f', 'r_squared'}
        assert required.issubset(set(actual.columns))

    def test_all_methods(self):
        actual = pd.read_csv('/app/results/metric_impact.tsv', sep='\t')
        assert set(actual['tree_method']) == {'reference', 'upgma', 'nj', 'bme'}

    def test_pseudo_f_values(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/metric_impact.tsv', sep='\t')
        actual = actual.set_index('tree_method')
        for method, vals in exp['impact'].items():
            np.testing.assert_allclose(
                float(actual.loc[method, 'pseudo_f']), vals['pseudo_f'],
                rtol=0.05,
                err_msg=f"pseudo_f mismatch for {method}")

    def test_r_squared_values(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/metric_impact.tsv', sep='\t')
        actual = actual.set_index('tree_method')
        for method, vals in exp['impact'].items():
            np.testing.assert_allclose(
                float(actual.loc[method, 'r_squared']), vals['r_squared'],
                atol=0.02,
                err_msg=f"R² mismatch for {method}")


class TestVariancePartitioning:
    def test_all_components(self):
        actual = pd.read_csv('/app/results/variance_partitioning.tsv', sep='\t')
        expected = {'treatment_total', 'batch_total', 'treatment_unique',
                    'batch_unique', 'shared', 'residual'}
        assert set(actual['component']) == expected, \
            f"Missing components: {expected - set(actual['component'])}"

    def test_internal_consistency_treatment(self):
        """treatment_total ≈ treatment_unique + shared."""
        actual = pd.read_csv('/app/results/variance_partitioning.tsv', sep='\t')
        actual = actual.set_index('component')
        t_total = float(actual.loc['treatment_total', 'r_squared'])
        t_unique = float(actual.loc['treatment_unique', 'r_squared'])
        shared = float(actual.loc['shared', 'r_squared'])
        np.testing.assert_allclose(
            t_total, t_unique + shared, atol=0.02,
            err_msg="treatment_total != treatment_unique + shared")

    def test_internal_consistency_batch(self):
        """batch_total ≈ batch_unique + shared."""
        actual = pd.read_csv('/app/results/variance_partitioning.tsv', sep='\t')
        actual = actual.set_index('component')
        b_total = float(actual.loc['batch_total', 'r_squared'])
        b_unique = float(actual.loc['batch_unique', 'r_squared'])
        shared = float(actual.loc['shared', 'r_squared'])
        np.testing.assert_allclose(
            b_total, b_unique + shared, atol=0.02,
            err_msg="batch_total != batch_unique + shared")

    def test_components_sum_to_one(self):
        """treatment_unique + batch_unique + shared + residual ≈ 1.0."""
        actual = pd.read_csv('/app/results/variance_partitioning.tsv', sep='\t')
        actual = actual.set_index('component')
        total = (float(actual.loc['treatment_unique', 'r_squared']) +
                 float(actual.loc['batch_unique', 'r_squared']) +
                 float(actual.loc['shared', 'r_squared']) +
                 float(actual.loc['residual', 'r_squared']))
        np.testing.assert_allclose(
            total, 1.0, atol=0.02,
            err_msg="Variance components don't sum to 1.0")

    def test_values(self):
        exp = _get_expected()
        actual = pd.read_csv('/app/results/variance_partitioning.tsv', sep='\t')
        actual = actual.set_index('component')
        for comp, expected_r2 in exp['vp'].items():
            np.testing.assert_allclose(
                float(actual.loc[comp, 'r_squared']), expected_r2,
                atol=0.03,
                err_msg=f"Variance partition mismatch for {comp}")


class TestAssessment:
    def test_valid_value(self):
        with open('/app/results/assessment.txt') as f:
            val = f.read().strip()
        assert val in ('genuine', 'confounded'), \
            f"Expected 'genuine' or 'confounded', got '{val}'"

    def test_correct(self):
        exp = _get_expected()
        with open('/app/results/assessment.txt') as f:
            val = f.read().strip()
        assert val == exp['assessment'], \
            f"Expected '{exp['assessment']}', got '{val}'"

    def test_consistent_with_partition(self):
        """Assessment should match variance partitioning."""
        actual = pd.read_csv('/app/results/variance_partitioning.tsv', sep='\t')
        actual = actual.set_index('component')
        t_unique = float(actual.loc['treatment_unique', 'r_squared'])
        b_unique = float(actual.loc['batch_unique', 'r_squared'])

        with open('/app/results/assessment.txt') as f:
            val = f.read().strip()

        if t_unique > b_unique:
            assert val == 'genuine', \
                "treatment_unique > batch_unique but assessment != genuine"
        else:
            assert val == 'confounded', \
                "batch_unique >= treatment_unique but assessment != confounded"
