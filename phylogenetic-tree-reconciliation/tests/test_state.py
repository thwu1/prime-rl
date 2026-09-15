#!/usr/bin/env python3
"""Tests for microbiome phylogenetic audit task.

Independently computes all expected results from input data using scikit-bio,
then compares against the agent's output files.
"""

import json
import os
import pytest
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from skbio import DistanceMatrix, TreeNode
from skbio.tree import nj
from skbio.diversity import beta_diversity, alpha_diversity
from skbio.stats.distance import permanova


@pytest.fixture(scope="session")
def input_data():
    """Load all input data files."""
    dm_df = pd.read_csv("/app/data/pairwise_distances.tsv", sep="\t", index_col=0)
    otu_names = list(dm_df.index)
    dm_array = dm_df.values.astype(float)
    dm = DistanceMatrix(dm_array, ids=otu_names)

    upgma_tree = TreeNode.read("/app/data/provided_tree.nwk")

    counts_df = pd.read_csv("/app/data/otu_counts.tsv", sep="\t", index_col=0)
    sample_names = list(counts_df.index)
    counts_matrix = counts_df.values.astype(int)

    meta_df = pd.read_csv("/app/data/sample_metadata.tsv", sep="\t", index_col=0)
    groups = meta_df["Group"].values
    taxa = list(counts_df.columns)

    return {
        "dm": dm,
        "dm_array": dm_array,
        "otu_names": otu_names,
        "upgma_tree": upgma_tree,
        "counts_matrix": counts_matrix,
        "sample_names": sample_names,
        "groups": groups,
        "taxa": taxa,
    }


@pytest.fixture(scope="session")
def expected(input_data):
    """Independently compute all expected results."""
    dm = input_data["dm"]
    dm_array = input_data["dm_array"]
    otu_names = input_data["otu_names"]
    upgma_tree = input_data["upgma_tree"]
    counts_matrix = input_data["counts_matrix"]
    sample_names = input_data["sample_names"]
    groups = input_data["groups"]
    taxa = input_data["taxa"]

    # Cophenetic correlation (fidelity_score)
    upgma_coph = upgma_tree.cophenet()
    upgma_coph = upgma_coph.filter(otu_names)
    n = len(otu_names)
    coph_vals, orig_vals = [], []
    for i in range(n):
        for j in range(i + 1, n):
            coph_vals.append(upgma_coph[otu_names[i], otu_names[j]])
            orig_vals.append(dm_array[i, j])
    corr_r, _ = pearsonr(coph_vals, orig_vals)

    # NJ tree rooted at midpoint
    nj_tree = nj(dm)
    nj_tree = nj_tree.root_at_midpoint()

    # Normalized Robinson-Foulds distance (topology_divergence)
    rf = upgma_tree.compare_rfd(nj_tree, proportion=True)

    # Weighted UniFrac (community_distances)
    unifrac_dm = beta_diversity(
        "weighted_unifrac",
        counts_matrix,
        ids=sample_names,
        taxa=taxa,
        tree=nj_tree,
        validate=True,
    )

    # PERMANOVA (group_comparison)
    grouping = pd.DataFrame({"Group": groups}, index=sample_names)
    perm_result = permanova(
        unifrac_dm, grouping, column="Group", permutations=999, seed=0
    )

    # Faith PD (sample_phylo_diversity)
    faith_values = alpha_diversity(
        "faith_pd", counts_matrix, ids=sample_names, taxa=taxa, tree=nj_tree
    )

    # Highest PD group
    faith_df = pd.DataFrame(
        {"SampleID": sample_names, "Faith_PD": faith_values.values, "Group": groups}
    )
    group_means = faith_df.groupby("Group")["Faith_PD"].mean()
    highest_group = group_means.idxmax()

    return {
        "fidelity_score": corr_r,
        "nj_tree": nj_tree,
        "topology_divergence": rf,
        "unifrac_dm": unifrac_dm,
        "permanova_f": perm_result["test statistic"],
        "permanova_p": perm_result["p-value"],
        "faith_values": faith_values,
        "highest_group": highest_group,
    }


# ---------------------------------------------------------------------------
# Tree Assessment JSON
# ---------------------------------------------------------------------------
class TestTreeAssessment:
    def test_file_exists(self):
        assert os.path.exists("/app/results/tree_assessment.json"), (
            "Missing /app/results/tree_assessment.json"
        )

    def test_valid_json_with_keys(self):
        with open("/app/results/tree_assessment.json") as f:
            data = json.load(f)
        assert "fidelity_score" in data, "Missing key 'fidelity_score'"
        assert "topology_divergence" in data, "Missing key 'topology_divergence'"
        assert "original_conclusion_valid" in data, "Missing key 'original_conclusion_valid'"

    def test_fidelity_score(self, expected):
        with open("/app/results/tree_assessment.json") as f:
            data = json.load(f)
        agent_r = float(data["fidelity_score"])
        exp_r = expected["fidelity_score"]
        assert abs(agent_r - exp_r) < 0.02, (
            f"fidelity_score={agent_r:.4f}, expected {exp_r:.4f}"
        )

    def test_fidelity_below_one(self):
        with open("/app/results/tree_assessment.json") as f:
            data = json.load(f)
        agent_r = float(data["fidelity_score"])
        assert agent_r < 0.999, (
            "fidelity_score should be < 1 for a tree that distorts the distances"
        )

    def test_topology_divergence(self, expected):
        with open("/app/results/tree_assessment.json") as f:
            data = json.load(f)
        agent_td = float(data["topology_divergence"])
        exp_td = expected["topology_divergence"]
        assert abs(agent_td - exp_td) < 0.1, (
            f"topology_divergence={agent_td:.4f}, expected {exp_td:.4f}"
        )

    def test_topology_divergence_nonzero(self):
        with open("/app/results/tree_assessment.json") as f:
            data = json.load(f)
        agent_td = float(data["topology_divergence"])
        assert agent_td > 0.0, (
            "topology_divergence should be > 0 (trees should differ)"
        )

    def test_original_conclusion_invalid(self):
        with open("/app/results/tree_assessment.json") as f:
            data = json.load(f)
        valid = data["original_conclusion_valid"]
        assert valid is False or valid == 0, (
            "original_conclusion_valid should be false — corrected analysis "
            "should show significant group differences"
        )


# ---------------------------------------------------------------------------
# Corrected Tree
# ---------------------------------------------------------------------------
class TestCorrectedTree:
    def test_file_exists(self):
        assert os.path.exists("/app/results/corrected_tree.nwk"), (
            "Missing /app/results/corrected_tree.nwk"
        )

    def test_tree_parseable(self):
        tree = TreeNode.read("/app/results/corrected_tree.nwk")
        assert tree is not None

    def test_correct_tips(self, input_data):
        tree = TreeNode.read("/app/results/corrected_tree.nwk")
        tips = {t.name for t in tree.tips()}
        assert tips == set(input_data["otu_names"]), (
            f"Tree tips {tips} != expected {set(input_data['otu_names'])}"
        )

    def test_tree_is_rooted(self):
        tree = TreeNode.read("/app/results/corrected_tree.nwk")
        assert len(tree.children) == 2, (
            f"Expected rooted tree (2 root children), got {len(tree.children)}"
        )

    def test_topology_matches(self, expected):
        agent_tree = TreeNode.read("/app/results/corrected_tree.nwk")
        expected_tree = expected["nj_tree"]
        rf = agent_tree.compare_rfd(expected_tree)
        assert rf == 0.0, (
            f"Corrected tree topology differs from expected (RF distance = {rf})"
        )


# ---------------------------------------------------------------------------
# Community Distances (weighted UniFrac)
# ---------------------------------------------------------------------------
class TestCommunityDistances:
    def test_file_exists(self):
        assert os.path.exists("/app/results/community_distances.tsv"), (
            "Missing /app/results/community_distances.tsv"
        )

    def test_matrix_shape(self, input_data):
        df = pd.read_csv("/app/results/community_distances.tsv", sep="\t", index_col=0)
        n = len(input_data["sample_names"])
        assert df.shape == (n, n), f"Expected {n}x{n}, got {df.shape}"

    def test_symmetric(self):
        df = pd.read_csv("/app/results/community_distances.tsv", sep="\t", index_col=0)
        arr = df.values.astype(float)
        assert np.allclose(arr, arr.T, atol=1e-6), "Distance matrix not symmetric"

    def test_zero_diagonal(self):
        df = pd.read_csv("/app/results/community_distances.tsv", sep="\t", index_col=0)
        diag = np.diag(df.values.astype(float))
        assert np.allclose(diag, 0, atol=1e-6), "Diagonal should be zero"

    def test_values_correct(self, expected, input_data):
        df = pd.read_csv("/app/results/community_distances.tsv", sep="\t", index_col=0)
        expected_dm = expected["unifrac_dm"]
        sample_names = input_data["sample_names"]

        for i in range(len(sample_names)):
            for j in range(i + 1, len(sample_names)):
                si, sj = sample_names[i], sample_names[j]
                agent_val = float(df.loc[si, sj])
                expected_val = expected_dm[si, sj]
                assert abs(agent_val - expected_val) < 0.001, (
                    f"Distance[{si},{sj}]: {agent_val:.6f} != {expected_val:.6f}"
                )


# ---------------------------------------------------------------------------
# Group Comparison (PERMANOVA)
# ---------------------------------------------------------------------------
class TestGroupComparison:
    def test_file_exists(self):
        assert os.path.exists("/app/results/group_comparison.txt"), (
            "Missing /app/results/group_comparison.txt"
        )

    def test_format(self):
        with open("/app/results/group_comparison.txt") as f:
            lines = f.read().strip().split("\n")
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"
        assert lines[0].startswith("statistic"), (
            f"Line 1 must start with 'statistic', got: {lines[0]}"
        )
        assert lines[1].startswith("p-value"), (
            f"Line 2 must start with 'p-value', got: {lines[1]}"
        )

    def test_statistic_value(self, expected):
        with open("/app/results/group_comparison.txt") as f:
            lines = f.read().strip().split("\n")
        agent_f = float(lines[0].split("\t")[1])
        exp_f = expected["permanova_f"]
        rel_diff = abs(agent_f - exp_f) / max(abs(exp_f), 1e-10)
        assert rel_diff < 0.05, (
            f"Statistic={agent_f:.4f}, expected {exp_f:.4f} (rel diff={rel_diff:.4f})"
        )

    def test_p_value(self, expected):
        with open("/app/results/group_comparison.txt") as f:
            lines = f.read().strip().split("\n")
        agent_p = float(lines[1].split("\t")[1])
        exp_p = expected["permanova_p"]
        assert abs(agent_p - exp_p) < 0.02, (
            f"p-value={agent_p:.4f}, expected {exp_p:.4f}"
        )

    def test_significant(self, expected):
        """After correcting the tree, group differences should be significant."""
        with open("/app/results/group_comparison.txt") as f:
            lines = f.read().strip().split("\n")
        agent_p = float(lines[1].split("\t")[1])
        assert agent_p < 0.05, (
            f"p-value={agent_p:.4f}, expected significant (<0.05) after correction"
        )


# ---------------------------------------------------------------------------
# Sample Phylogenetic Diversity (Faith PD)
# ---------------------------------------------------------------------------
class TestSamplePhyloDiversity:
    def test_file_exists(self):
        assert os.path.exists("/app/results/sample_phylo_diversity.tsv"), (
            "Missing /app/results/sample_phylo_diversity.tsv"
        )

    def test_all_samples_present(self, input_data):
        df = pd.read_csv("/app/results/sample_phylo_diversity.tsv", sep="\t")
        assert set(df["SampleID"]) == set(input_data["sample_names"]), (
            f"Sample IDs mismatch: {set(df['SampleID'])} vs "
            f"{set(input_data['sample_names'])}"
        )

    def test_values_correct(self, expected, input_data):
        df = pd.read_csv(
            "/app/results/sample_phylo_diversity.tsv", sep="\t"
        ).set_index("SampleID")
        exp_faith = expected["faith_values"]
        for sid in input_data["sample_names"]:
            agent_val = float(df.loc[sid, "PD"])
            expected_val = float(exp_faith[sid])
            assert abs(agent_val - expected_val) < 0.01, (
                f"PD[{sid}]: {agent_val:.4f} != {expected_val:.4f}"
            )


# ---------------------------------------------------------------------------
# Most Diverse Group
# ---------------------------------------------------------------------------
class TestMostDiverseGroup:
    def test_file_exists(self):
        assert os.path.exists("/app/results/most_diverse_group.txt"), (
            "Missing /app/results/most_diverse_group.txt"
        )

    def test_correct_group(self, expected):
        with open("/app/results/most_diverse_group.txt") as f:
            agent_group = f.read().strip()
        exp_group = expected["highest_group"]
        assert agent_group == exp_group, (
            f"Most diverse group '{agent_group}' != expected '{exp_group}'"
        )
