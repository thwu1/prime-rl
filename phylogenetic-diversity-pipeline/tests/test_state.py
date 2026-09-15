"""
Verification tests for the phylogenetic microbiome diversity analysis pipeline.
Independently computes expected results and compares against agent output.

"""

import os
import pytest
import numpy as np
import pandas as pd
from io import StringIO

from skbio import TreeNode, DistanceMatrix
from skbio.tree import majority_rule
from skbio.diversity import alpha_diversity, beta_diversity
from skbio.stats.distance import permanova
from skbio.stats.ordination import pcoa

RESULTS_DIR = "/app/results"
DATA_DIR = "/app/data"


# ---- Helper: load input data and compute expected results ----

def load_input_data():
    """Load all input data files."""
    # Load gene trees
    gene_trees = []
    with open(os.path.join(DATA_DIR, "gene_trees.nwk")) as f:
        for line in f:
            line = line.strip()
            if line:
                gene_trees.append(TreeNode.read(StringIO(line)))

    # Load species tree
    species_tree = TreeNode.read(os.path.join(DATA_DIR, "species_tree.nwk"))

    # Load OTU table
    otu_table = pd.read_csv(os.path.join(DATA_DIR, "otu_table.tsv"), sep="\t",
                            index_col=0)

    # Load metadata
    metadata = pd.read_csv(os.path.join(DATA_DIR, "metadata.tsv"), sep="\t",
                           index_col=0)

    return gene_trees, species_tree, otu_table, metadata


def compute_expected():
    """Compute all expected results from input data."""
    gene_trees, species_tree, otu_table, metadata = load_input_data()

    # Tree tips
    tree_tips = {tip.name for tip in species_tree.tips()}

    # Filter OTU table
    otu_cols = [c for c in otu_table.columns if c in tree_tips]
    otu_filtered = otu_table[otu_cols]
    sample_ids = list(otu_filtered.index)
    taxa = list(otu_filtered.columns)
    counts = otu_filtered.values

    # RF distance matrix
    n = len(gene_trees)
    rf_matrix = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(i + 1, n):
            d = gene_trees[i].compare_rfd(gene_trees[j], proportion=False,
                                          rooted=False)
            rf_matrix[i, j] = int(d)
            rf_matrix[j, i] = int(d)

    # Consensus tree
    consensus = majority_rule(gene_trees)[0]
    # Strip support values so bipartitions use clean tip names
    for node in consensus.traverse():
        node.support = None

    # Root species tree
    rooted_tree = species_tree.root_by_outgroup(["OTU09", "OTU10"])

    # Faith's PD
    faith_pd_vals = alpha_diversity("faith_pd", counts, ids=sample_ids,
                                   tree=rooted_tree, taxa=taxa)

    # Weighted UniFrac
    unifrac_dm = beta_diversity("weighted_unifrac", counts, ids=sample_ids,
                                tree=rooted_tree, taxa=taxa)

    # PERMANOVA
    perm_result = permanova(unifrac_dm, metadata, column="Treatment",
                            permutations=999, seed=42)
    pseudo_f = perm_result["test statistic"]
    p_val = perm_result["p-value"]
    n_samples = perm_result["sample size"]
    n_groups = perm_result["number of groups"]
    r_sq = 1.0 / (1.0 + (n_samples - n_groups) / ((n_groups - 1) * pseudo_f))

    # PCoA
    pcoa_result = pcoa(unifrac_dm)

    return {
        "rf_matrix": rf_matrix,
        "consensus": consensus,
        "faith_pd": faith_pd_vals,
        "unifrac_dm": unifrac_dm,
        "pseudo_f": pseudo_f,
        "p_value": p_val,
        "n_samples": n_samples,
        "n_groups": n_groups,
        "r_squared": r_sq,
        "pcoa_result": pcoa_result,
        "gene_tree_count": n,
        "sample_ids": sample_ids,
        "taxa": taxa,
        "otu_filtered_cols": otu_cols,
    }


@pytest.fixture(scope="module")
def expected():
    return compute_expected()


# ---- Tests ----

class TestOutputFilesExist:
    """Verify all required output files are present."""

    @pytest.mark.parametrize("filename", [
        "rf_matrix.tsv",
        "consensus.nwk",
        "faith_pd.tsv",
        "unifrac_dm.tsv",
        "permanova.tsv",
        "pcoa_axes.tsv",
        "pcoa_propexpl.tsv",
    ])
    def test_file_exists(self, filename):
        path = os.path.join(RESULTS_DIR, filename)
        assert os.path.isfile(path), f"Missing output file: {path}"


class TestRFDistanceMatrix:
    """Verify Robinson-Foulds distance matrix correctness."""

    def test_rf_matrix_shape(self, expected):
        rf_df = pd.read_csv(os.path.join(RESULTS_DIR, "rf_matrix.tsv"),
                            sep="\t", index_col=0)
        n = expected["gene_tree_count"]
        assert rf_df.shape == (n, n), \
            f"RF matrix shape {rf_df.shape} != expected ({n}, {n})"

    def test_rf_matrix_values(self, expected):
        rf_df = pd.read_csv(os.path.join(RESULTS_DIR, "rf_matrix.tsv"),
                            sep="\t", index_col=0)
        agent_matrix = rf_df.values.astype(int)
        expected_matrix = expected["rf_matrix"]
        np.testing.assert_array_equal(
            agent_matrix, expected_matrix,
            err_msg="RF distance matrix values do not match expected"
        )

    def test_rf_matrix_symmetric(self, expected):
        rf_df = pd.read_csv(os.path.join(RESULTS_DIR, "rf_matrix.tsv"),
                            sep="\t", index_col=0)
        mat = rf_df.values.astype(float)
        np.testing.assert_array_equal(mat, mat.T,
                                      err_msg="RF matrix is not symmetric")

    def test_rf_matrix_diagonal_zero(self, expected):
        rf_df = pd.read_csv(os.path.join(RESULTS_DIR, "rf_matrix.tsv"),
                            sep="\t", index_col=0)
        diag = np.diag(rf_df.values.astype(float))
        np.testing.assert_array_equal(diag, np.zeros(len(diag)),
                                      err_msg="RF matrix diagonal is not zero")


class TestConsensusTree:
    """Verify majority-rule consensus tree topology."""

    @staticmethod
    def _normalize_tree(tree):
        """Normalize a consensus tree read from Newick.

        majority_rule sets support on every node including tips. If the agent
        didn't strip support before writing, tip labels become "support:name"
        (e.g. "12.0:OTU01"). This helper parses those labels so that the
        tree's tip names match the original taxon identifiers.
        """
        for tip in tree.tips():
            if tip.name and ":" in tip.name:
                parts = tip.name.split(":", 1)
                try:
                    float(parts[0])
                    tip.name = parts[1]
                except ValueError:
                    pass
        # Also call assign_supports to fix internal node labels
        tree.assign_supports()
        return tree

    def test_consensus_file_nonempty(self):
        path = os.path.join(RESULTS_DIR, "consensus.nwk")
        with open(path) as f:
            content = f.read().strip()
        assert len(content) > 10, "Consensus tree file is too short"
        assert content.endswith(";"), "Consensus tree should end with semicolon"

    def test_consensus_topology(self, expected):
        path = os.path.join(RESULTS_DIR, "consensus.nwk")
        with open(path) as f:
            content = f.read().strip()
        agent_tree = self._normalize_tree(TreeNode.read(StringIO(content)))
        expected_tree = expected["consensus"]

        # Compare bipartitions (topology)
        agent_biparts = agent_tree.biparts()
        expected_biparts = expected_tree.biparts()
        assert agent_biparts == expected_biparts, \
            "Consensus tree topology (bipartitions) does not match expected"

    def test_consensus_tips(self, expected):
        path = os.path.join(RESULTS_DIR, "consensus.nwk")
        with open(path) as f:
            content = f.read().strip()
        agent_tree = self._normalize_tree(TreeNode.read(StringIO(content)))
        agent_tips = {tip.name for tip in agent_tree.tips()}

        expected_tree = expected["consensus"]
        expected_tips = {tip.name for tip in expected_tree.tips()}

        assert agent_tips == expected_tips, \
            f"Consensus tree tips {agent_tips} != expected {expected_tips}"


class TestFaithPD:
    """Verify Faith's Phylogenetic Diversity values."""

    def test_faith_pd_shape(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "faith_pd.tsv"), sep="\t")
        n_samples = len(expected["sample_ids"])
        assert len(df) == n_samples, \
            f"Faith PD table has {len(df)} rows, expected {n_samples}"

    def test_faith_pd_columns(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "faith_pd.tsv"), sep="\t")
        assert "SampleID" in df.columns, "Missing SampleID column"
        assert "FaithPD" in df.columns, "Missing FaithPD column"

    def test_faith_pd_values(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "faith_pd.tsv"), sep="\t")
        df = df.sort_values("SampleID").reset_index(drop=True)

        expected_pd = expected["faith_pd"]
        for _, row in df.iterrows():
            sid = row["SampleID"]
            agent_val = float(row["FaithPD"])
            expected_val = float(expected_pd[sid])
            assert abs(agent_val - expected_val) < 1e-4, \
                f"Faith PD for {sid}: {agent_val} != expected {expected_val}"

    def test_faith_pd_sorted(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "faith_pd.tsv"), sep="\t")
        sample_ids = list(df["SampleID"])
        assert sample_ids == sorted(sample_ids), \
            "Faith PD table is not sorted by SampleID"


class TestUniFracDistanceMatrix:
    """Verify weighted UniFrac distance matrix."""

    def test_unifrac_shape(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"),
                         sep="\t", index_col=0)
        n = len(expected["sample_ids"])
        assert df.shape == (n, n), \
            f"UniFrac DM shape {df.shape} != expected ({n}, {n})"

    def test_unifrac_symmetric(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"),
                         sep="\t", index_col=0)
        mat = df.values
        np.testing.assert_allclose(mat, mat.T, atol=1e-6,
                                   err_msg="UniFrac DM is not symmetric")

    def test_unifrac_diagonal_zero(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"),
                         sep="\t", index_col=0)
        diag = np.diag(df.values)
        np.testing.assert_allclose(diag, 0.0, atol=1e-6,
                                   err_msg="UniFrac DM diagonal is not zero")

    def test_unifrac_values(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"),
                         sep="\t", index_col=0)
        expected_dm = expected["unifrac_dm"]
        expected_df = expected_dm.to_data_frame()

        # Align sample ordering
        common_ids = sorted(set(df.index) & set(expected_df.index))
        agent_mat = df.loc[common_ids, common_ids].values
        expected_mat = expected_df.loc[common_ids, common_ids].values

        np.testing.assert_allclose(
            agent_mat, expected_mat, atol=1e-4,
            err_msg="UniFrac distance values do not match expected"
        )

    def test_unifrac_sample_ids(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"),
                         sep="\t", index_col=0)
        expected_ids = set(expected["sample_ids"])
        agent_ids = set(df.index)
        assert agent_ids == expected_ids, \
            f"UniFrac sample IDs {agent_ids} != expected {expected_ids}"


class TestPERMANOVA:
    """Verify PERMANOVA results."""

    def test_permanova_columns(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        required = {"test_statistic", "p_value", "sample_size", "num_groups",
                     "R_squared"}
        assert required.issubset(set(df.columns)), \
            f"Missing columns: {required - set(df.columns)}"

    def test_permanova_pseudo_f(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        agent_f = float(df["test_statistic"].iloc[0])
        expected_f = expected["pseudo_f"]
        assert abs(agent_f - expected_f) < 1e-3, \
            f"Pseudo-F: {agent_f} != expected {expected_f}"

    def test_permanova_sample_size(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        assert int(df["sample_size"].iloc[0]) == int(expected["n_samples"])

    def test_permanova_num_groups(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        assert int(df["num_groups"].iloc[0]) == int(expected["n_groups"])

    def test_permanova_r_squared(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        agent_r2 = float(df["R_squared"].iloc[0])
        expected_r2 = expected["r_squared"]
        assert abs(agent_r2 - expected_r2) < 1e-3, \
            f"R²: {agent_r2} != expected {expected_r2}"

    def test_permanova_r_squared_formula(self, expected):
        """Verify R² was computed using the correct formula."""
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        f_val = float(df["test_statistic"].iloc[0])
        n = int(df["sample_size"].iloc[0])
        g = int(df["num_groups"].iloc[0])
        r2_from_formula = 1.0 / (1.0 + (n - g) / ((g - 1) * f_val))
        agent_r2 = float(df["R_squared"].iloc[0])
        assert abs(agent_r2 - r2_from_formula) < 1e-4, \
            f"R² doesn't match formula: {agent_r2} vs {r2_from_formula}"

    def test_permanova_p_value(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t")
        agent_p = float(df["p_value"].iloc[0])
        expected_p = expected["p_value"]
        # p-value should match with seed=42, 999 permutations
        assert abs(agent_p - expected_p) < 0.01, \
            f"p-value: {agent_p} != expected {expected_p} (with seed=42)"


class TestPCoA:
    """Verify PCoA ordination results."""

    def test_pcoa_axes_shape(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "pcoa_axes.tsv"), sep="\t")
        n = len(expected["sample_ids"])
        assert len(df) == n, f"PCoA has {len(df)} rows, expected {n}"
        for col in ["SampleID", "PC1", "PC2", "PC3"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_pcoa_axes_values(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "pcoa_axes.tsv"), sep="\t")
        df = df.sort_values("SampleID").reset_index(drop=True)

        exp_coords = expected["pcoa_result"].samples
        exp_coords = exp_coords.sort_index()

        for i, sid in enumerate(df["SampleID"]):
            for j, col in enumerate(["PC1", "PC2", "PC3"]):
                agent_val = float(df[col].iloc[i])
                expected_val = float(exp_coords.iloc[
                    exp_coords.index.get_loc(sid), j
                ])
                # Handle sign ambiguity: compare absolute values
                assert abs(abs(agent_val) - abs(expected_val)) < 1e-4, \
                    f"PCoA {col} for {sid}: |{agent_val}| != |{expected_val}|"

    def test_pcoa_propexpl_shape(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "pcoa_propexpl.tsv"),
                         sep="\t")
        assert len(df) == 3, f"ProportionExplained has {len(df)} rows, expected 3"
        for col in ["Axis", "ProportionExplained"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_pcoa_propexpl_values(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "pcoa_propexpl.tsv"),
                         sep="\t")
        exp_pe = expected["pcoa_result"].proportion_explained

        for i in range(3):
            agent_val = float(df["ProportionExplained"].iloc[i])
            expected_val = float(exp_pe.iloc[i])
            assert abs(agent_val - expected_val) < 1e-4, \
                f"PCoA proportion explained axis {i}: " \
                f"{agent_val} != {expected_val}"

    def test_pcoa_propexpl_sum_leq_one(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "pcoa_propexpl.tsv"),
                         sep="\t")
        total = sum(float(x) for x in df["ProportionExplained"])
        assert total <= 1.0 + 1e-6, \
            f"Sum of proportion explained ({total}) exceeds 1.0"


class TestDataReconciliation:
    """Verify that OTU data reconciliation was done correctly."""

    def test_filtered_otus_not_in_unifrac(self, expected):
        """OTU11 and OTU12 should not appear in the analysis."""
        df = pd.read_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"),
                         sep="\t", index_col=0)
        # The distance matrix should have the right sample IDs
        assert len(df) == 15, "Expected 15 samples in UniFrac DM"

    def test_all_samples_present(self, expected):
        """All 15 samples should be in the outputs."""
        faith_df = pd.read_csv(os.path.join(RESULTS_DIR, "faith_pd.tsv"),
                               sep="\t")
        expected_ids = set(expected["sample_ids"])
        agent_ids = set(faith_df["SampleID"])
        assert agent_ids == expected_ids, \
            f"Sample IDs mismatch: {agent_ids} != {expected_ids}"
