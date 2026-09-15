"""Tests for bulk RNA-seq deconvolution and composition-aware DE analysis."""

import pytest
import pandas as pd
import numpy as np
from scipy.optimize import nnls
import os

RESULTS_DIR = '/app/results'

# Known DE genes by construction (seed 42): genes 400-429
KNOWN_DE_GENES = [f'GENE_{i:04d}' for i in range(400, 430)]
KNOWN_UP_GENES = [f'GENE_{i:04d}' for i in range(400, 415)]
KNOWN_DOWN_GENES = [f'GENE_{i:04d}' for i in range(415, 430)]

# Cell-type marker gene ranges (by construction)
MARKER_GENES = [f'GENE_{i:04d}' for i in range(100)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def proportions():
    return pd.read_csv(f'{RESULTS_DIR}/proportions.csv', index_col=0)


@pytest.fixture(scope='module')
def da_results():
    return pd.read_csv(f'{RESULTS_DIR}/da_results.csv')


@pytest.fixture(scope='module')
def de_results():
    return pd.read_csv(f'{RESULTS_DIR}/de_results.csv')


@pytest.fixture(scope='module')
def sig_genes():
    with open(f'{RESULTS_DIR}/significant_genes.txt') as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture(scope='module')
def metadata():
    return pd.read_csv('/app/metadata.csv')


@pytest.fixture(scope='module')
def reference_proportions():
    """Independently compute NNLS proportions as reference."""
    counts = pd.read_csv('/app/counts.csv', index_col=0)
    signature = pd.read_csv('/app/signature.csv', index_col=0)
    n_samples = counts.shape[1]
    n_ct = signature.shape[1]
    props = np.zeros((n_samples, n_ct))
    for i in range(n_samples):
        y = counts.iloc[:, i].values
        A = signature.values
        x, _ = nnls(A, y)
        if x.sum() > 0:
            x = x / x.sum()
        props[i] = x
    return pd.DataFrame(props, index=counts.columns, columns=signature.columns)


# ---------------------------------------------------------------------------
# Output file existence and format
# ---------------------------------------------------------------------------

class TestOutputFiles:

    def test_proportions_exists(self):
        assert os.path.exists(f'{RESULTS_DIR}/proportions.csv')

    def test_da_results_exists(self):
        assert os.path.exists(f'{RESULTS_DIR}/da_results.csv')

    def test_de_results_exists(self):
        assert os.path.exists(f'{RESULTS_DIR}/de_results.csv')

    def test_significant_genes_exists(self):
        assert os.path.exists(f'{RESULTS_DIR}/significant_genes.txt')


# ---------------------------------------------------------------------------
# Cell type proportion estimates
# ---------------------------------------------------------------------------

class TestProportions:

    def test_shape(self, proportions):
        assert proportions.shape == (40, 5), \
            f"Expected (40, 5), got {proportions.shape}"

    def test_non_negative(self, proportions):
        assert (proportions.values >= -0.01).all(), \
            "Found negative proportions"

    def test_sum_to_one(self, proportions):
        row_sums = proportions.sum(axis=1)
        assert np.allclose(row_sums, 1.0, atol=0.15), \
            f"Row sums deviate from 1: min={row_sums.min():.3f}, max={row_sums.max():.3f}"

    def test_accuracy_vs_nnls(self, proportions, reference_proportions):
        """Estimated proportions should correlate with NNLS reference."""
        for ct in reference_proportions.columns:
            matched = [c for c in proportions.columns if ct.lower() in c.lower()]
            assert len(matched) > 0, f"Column matching '{ct}' not found"
            ref = reference_proportions[ct].values
            est = proportions[matched[0]].values
            corr = np.corrcoef(ref, est)[0, 1]
            assert corr > 0.80, \
                f"Low correlation for {ct}: r={corr:.3f}"

    def test_tcells_higher_in_treatment(self, proportions, metadata):
        t_col = [c for c in proportions.columns if 't_cell' in c.lower()]
        assert len(t_col) > 0, "T_cells column not found"
        ctrl = proportions.loc[metadata['condition'].values == 'control', t_col[0]]
        treat = proportions.loc[metadata['condition'].values == 'treatment', t_col[0]]
        assert treat.mean() > ctrl.mean(), \
            f"T cells should increase: ctrl={ctrl.mean():.3f} treat={treat.mean():.3f}"

    def test_bcells_lower_in_treatment(self, proportions, metadata):
        b_col = [c for c in proportions.columns if 'b_cell' in c.lower()]
        assert len(b_col) > 0, "B_cells column not found"
        ctrl = proportions.loc[metadata['condition'].values == 'control', b_col[0]]
        treat = proportions.loc[metadata['condition'].values == 'treatment', b_col[0]]
        assert treat.mean() < ctrl.mean(), \
            f"B cells should decrease: ctrl={ctrl.mean():.3f} treat={treat.mean():.3f}"


# ---------------------------------------------------------------------------
# Differential abundance
# ---------------------------------------------------------------------------

class TestDifferentialAbundance:

    def test_columns(self, da_results):
        required = {'cell_type', 'log2fc', 'pvalue', 'padj'}
        assert required.issubset(set(da_results.columns)), \
            f"Missing columns: {required - set(da_results.columns)}"

    def test_all_cell_types_present(self, da_results):
        assert len(da_results) == 5, f"Expected 5 rows, got {len(da_results)}"

    def test_tcells_significant_increase(self, da_results):
        t_row = da_results[da_results['cell_type'].str.contains('T_cell', case=False)]
        assert len(t_row) > 0, "T_cells not in results"
        assert t_row.iloc[0]['log2fc'] > 0, "T cells log2fc should be positive"
        assert t_row.iloc[0]['padj'] < 0.05, "T cells change should be significant"

    def test_bcells_significant_decrease(self, da_results):
        b_row = da_results[da_results['cell_type'].str.contains('B_cell', case=False)]
        assert len(b_row) > 0, "B_cells not in results"
        assert b_row.iloc[0]['log2fc'] < 0, "B cells log2fc should be negative"
        assert b_row.iloc[0]['padj'] < 0.05, "B cells change should be significant"


# ---------------------------------------------------------------------------
# Composition-aware differential expression
# ---------------------------------------------------------------------------

class TestCompositionAwareDE:

    def test_columns(self, de_results):
        required = {'gene', 'log2fc', 'pvalue', 'padj'}
        assert required.issubset(set(de_results.columns)), \
            f"Missing columns: {required - set(de_results.columns)}"

    def test_gene_count(self, de_results):
        assert len(de_results) >= 450, \
            f"Expected ~500 gene results, got {len(de_results)}"

    def test_true_de_genes_detected(self, de_results):
        """At least 20 of 30 known DE genes must be detected at padj < 0.05."""
        sig = de_results[de_results['padj'] < 0.05]
        detected = set(sig['gene'].values) & set(KNOWN_DE_GENES)
        assert len(detected) >= 20, \
            f"Only {len(detected)}/30 true DE genes detected (need >= 20)"

    def test_up_genes_positive_lfc(self, de_results):
        for gene in KNOWN_UP_GENES:
            row = de_results[de_results['gene'] == gene]
            if len(row) > 0 and row.iloc[0]['padj'] < 0.05:
                assert row.iloc[0]['log2fc'] > 0, \
                    f"{gene} should be up (log2fc={row.iloc[0]['log2fc']:.3f})"

    def test_down_genes_negative_lfc(self, de_results):
        for gene in KNOWN_DOWN_GENES:
            row = de_results[de_results['gene'] == gene]
            if len(row) > 0 and row.iloc[0]['padj'] < 0.05:
                lfc = row.iloc[0]['log2fc']
                assert not np.isnan(lfc), \
                    f"{gene} has NaN log2fc"
                assert lfc < 0, \
                    f"{gene} should be down (log2fc={lfc:.3f})"

    def test_false_positive_rate(self, de_results):
        """Non-DE genes should have controlled FP rate."""
        non_de = de_results[~de_results['gene'].isin(KNOWN_DE_GENES)]
        fp = (non_de['padj'] < 0.05).sum()
        fp_rate = fp / len(non_de) if len(non_de) > 0 else 0
        assert fp_rate < 0.15, \
            f"FP rate too high: {fp_rate:.3f} ({fp}/{len(non_de)})"

    def test_composition_correction_reduces_marker_fps(self, de_results):
        """Cell-type marker genes should not be significant after
        composition correction — their apparent DE is driven by
        proportion shifts, not true per-gene expression changes."""
        sig_markers = de_results[
            (de_results['gene'].isin(MARKER_GENES)) &
            (de_results['padj'] < 0.05)
        ]
        assert len(sig_markers) < 30, \
            f"Too many marker genes significant ({len(sig_markers)}/100): " \
            "composition correction may be missing or insufficient"

    def test_significant_genes_file_consistency(self, sig_genes, de_results):
        expected = set(de_results[de_results['padj'] < 0.05]['gene'].values)
        actual = set(sig_genes)
        if len(expected) == 0:
            pytest.skip("No significant genes in de_results")
        overlap = len(expected & actual)
        assert overlap >= len(expected) * 0.8, \
            f"significant_genes.txt inconsistent with de_results: " \
            f"{overlap}/{len(expected)} overlap"
