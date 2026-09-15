"""
Tests for regulatory network reconstruction from multi-omic data.

"""

import csv
import json
import os
import pytest
import numpy as np

RESULTS_DIR = "/app/results"
SEQ_LEN = 800

# ── Ground truth ─────────────────────────────────────────────────────────────

GROUND_TRUTH_ROLES = {
    "TF_A": "activator",
    "TF_B": "repressor",
    "TF_C": "activator",
    "TF_D": "repressor",
    "TF_E": "activator",
    "TF_F": "activator",
    "TF_G": "repressor",
    "TF_H": "activator",
}

MASTER_REGULATOR = "TF_C"

COOPERATIVE_PAIR = ("TF_C", "TF_E")

GROUND_TRUTH_TEST_EXPR = {
    "GENE_151": 9.043,
    "GENE_152": 11.314,
    "GENE_153": 19.336,
    "GENE_154": 14.497,
    "GENE_155": 4.015,
    "GENE_156": 9.319,
    "GENE_157": 5.652,
    "GENE_158": 0.1,
    "GENE_159": 3.317,
    "GENE_160": 12.458,
    "GENE_161": 11.023,
    "GENE_162": 9.791,
    "GENE_163": 0.1,
    "GENE_164": 12.16,
    "GENE_165": 14.572,
    "GENE_166": 3.63,
    "GENE_167": 4.541,
    "GENE_168": 12.305,
    "GENE_169": 25.012,
    "GENE_170": 14.239,
    "GENE_171": 5.488,
    "GENE_172": 36.542,
    "GENE_173": 6.825,
    "GENE_174": 7.755,
    "GENE_175": 4.45,
    "GENE_176": 21.805,
    "GENE_177": 8.367,
    "GENE_178": 10.883,
    "GENE_179": 4.065,
    "GENE_180": 6.534,
    "GENE_181": 6.415,
    "GENE_182": 0.1,
    "GENE_183": 4.466,
    "GENE_184": 4.115,
    "GENE_185": 7.183,
    "GENE_186": 7.472,
    "GENE_187": 17.81,
    "GENE_188": 7.434,
    "GENE_189": 6.751,
    "GENE_190": 12.184,
    "GENE_191": 10.804,
    "GENE_192": 4.273,
    "GENE_193": 0.1,
    "GENE_194": 4.794,
    "GENE_195": 8.349,
    "GENE_196": 14.45,
    "GENE_197": 18.825,
    "GENE_198": 3.994,
    "GENE_199": 14.811,
    "GENE_200": 7.883,
}

ALL_TF_NAMES = {f"TF_{c}" for c in "ABCDEFGH"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def r_squared(y_true, y_pred):
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot == 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


# ── Tests ────────────────────────────────────────────────────────────────────


class TestOutputFilesExist:
    def test_tf_roles_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "tf_roles.json"))

    def test_master_regulator_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "master_regulator.txt"))

    def test_predictions_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "predictions.tsv"))

    def test_functional_binding_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "functional_binding.bed"))

    def test_regulatory_network_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "regulatory_network.json"))


class TestTFRoles:
    def test_tf_roles_valid_json(self):
        with open(os.path.join(RESULTS_DIR, "tf_roles.json")) as f:
            roles = json.load(f)
        assert isinstance(roles, dict)

    def test_tf_roles_has_all_tfs(self):
        with open(os.path.join(RESULTS_DIR, "tf_roles.json")) as f:
            roles = json.load(f)
        for tf in GROUND_TRUTH_ROLES:
            assert tf in roles, f"Missing TF: {tf}"

    def test_tf_roles_valid_values(self):
        with open(os.path.join(RESULTS_DIR, "tf_roles.json")) as f:
            roles = json.load(f)
        for tf, role in roles.items():
            assert role in ("activator", "repressor"), (
                f"{tf} has invalid role '{role}'"
            )

    def test_tf_roles_accuracy(self):
        """At least 6 of 8 TF roles must be correctly identified."""
        with open(os.path.join(RESULTS_DIR, "tf_roles.json")) as f:
            roles = json.load(f)
        correct = sum(
            1 for tf, true_role in GROUND_TRUTH_ROLES.items()
            if roles.get(tf) == true_role
        )
        assert correct >= 6, (
            f"Only {correct}/8 TF roles correct (need >= 6)"
        )


class TestMasterRegulator:
    def test_master_regulator_correct(self):
        with open(os.path.join(RESULTS_DIR, "master_regulator.txt")) as f:
            predicted = f.read().strip()
        assert predicted == MASTER_REGULATOR, (
            f"Master regulator should be {MASTER_REGULATOR}, got '{predicted}'"
        )


class TestPredictions:
    def test_predictions_tsv_format(self):
        with open(os.path.join(RESULTS_DIR, "predictions.tsv")) as f:
            header = f.readline().strip().split("\t")
        assert "gene_id" in header, "Missing 'gene_id' column"
        assert "predicted_expression" in header, "Missing 'predicted_expression' column"

    def test_predictions_cover_all_test_genes(self):
        predicted_genes = set()
        with open(os.path.join(RESULTS_DIR, "predictions.tsv")) as f:
            header = f.readline().strip().split("\t")
            gi = header.index("gene_id")
            for line in f:
                parts = line.strip().split("\t")
                if parts:
                    predicted_genes.add(parts[gi])
        expected_genes = set(GROUND_TRUTH_TEST_EXPR.keys())
        missing = expected_genes - predicted_genes
        assert len(missing) == 0, f"Missing predictions for: {missing}"

    def test_predictions_r_squared(self):
        """Predicted test expression must achieve R^2 >= 0.50."""
        predictions = {}
        with open(os.path.join(RESULTS_DIR, "predictions.tsv")) as f:
            header = f.readline().strip().split("\t")
            gi = header.index("gene_id")
            ei = header.index("predicted_expression")
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) > max(gi, ei):
                    predictions[parts[gi]] = float(parts[ei])

        gene_ids = sorted(GROUND_TRUTH_TEST_EXPR.keys())
        y_true = [GROUND_TRUTH_TEST_EXPR[g] for g in gene_ids]
        y_pred = [predictions[g] for g in gene_ids]

        r2 = r_squared(y_true, y_pred)
        assert r2 >= 0.50, (
            f"R-squared = {r2:.4f}, need >= 0.50"
        )


class TestFunctionalBinding:
    BED_PATH = os.path.join(RESULTS_DIR, "functional_binding.bed")

    def _read_lines(self):
        with open(self.BED_PATH) as f:
            return [line.strip() for line in f if line.strip()]

    def test_minimum_site_count(self):
        lines = self._read_lines()
        assert len(lines) >= 100, (
            f"Only {len(lines)} binding sites (need >= 100)"
        )

    def test_bed6_tab_separated(self):
        lines = self._read_lines()
        for i, line in enumerate(lines):
            fields = line.split("\t")
            assert len(fields) == 6, (
                f"Line {i+1}: expected 6 tab fields, got {len(fields)}"
            )

    def test_coordinates_in_range(self):
        lines = self._read_lines()
        for i, line in enumerate(lines):
            fields = line.split("\t")
            start = int(fields[1])
            end = int(fields[2])
            assert 0 <= start < end <= SEQ_LEN, (
                f"Line {i+1}: invalid coords start={start} end={end}"
            )

    def test_all_tfs_represented(self):
        tfs_found = set()
        for line in self._read_lines():
            fields = line.split("\t")
            tfs_found.add(fields[3])
        missing = ALL_TF_NAMES - tfs_found
        assert not missing, f"Missing TFs in binding sites: {missing}"

    def test_score_is_numeric(self):
        lines = self._read_lines()
        for i, line in enumerate(lines):
            fields = line.split("\t")
            try:
                float(fields[4])
            except ValueError:
                pytest.fail(f"Line {i+1}: score '{fields[4]}' not numeric")

    def test_strand_values(self):
        lines = self._read_lines()
        for i, line in enumerate(lines):
            fields = line.split("\t")
            assert fields[5] in ("+", "-"), (
                f"Line {i+1}: invalid strand '{fields[5]}'"
            )


class TestRegulatoryNetwork:
    NET_PATH = os.path.join(RESULTS_DIR, "regulatory_network.json")

    def test_valid_json(self):
        with open(self.NET_PATH) as f:
            net = json.load(f)
        assert isinstance(net, dict)

    def test_has_required_keys(self):
        with open(self.NET_PATH) as f:
            net = json.load(f)
        for key in ("tf_roles", "master_regulator", "interactions"):
            assert key in net, f"Missing key: {key}"

    def test_interactions_is_list(self):
        with open(self.NET_PATH) as f:
            net = json.load(f)
        assert isinstance(net["interactions"], list), (
            "interactions must be an array"
        )

    def test_cooperative_pair_found(self):
        """The TF_C/TF_E cooperative interaction must be identified."""
        with open(self.NET_PATH) as f:
            net = json.load(f)
        interactions = net["interactions"]
        pair_found = False
        for edge in interactions:
            tfs_in_edge = {edge.get("tf1", ""), edge.get("tf2", "")}
            if tfs_in_edge == {"TF_C", "TF_E"}:
                edge_type = edge.get("type", "").lower()
                assert edge_type in ("cooperative", "synergistic"), (
                    f"TF_C/TF_E edge type should be cooperative, got '{edge_type}'"
                )
                pair_found = True
                break
        assert pair_found, (
            "Must identify cooperative interaction between TF_C and TF_E"
        )

    def test_master_regulator_in_network(self):
        with open(self.NET_PATH) as f:
            net = json.load(f)
        assert net["master_regulator"] == MASTER_REGULATOR, (
            f"Network master regulator should be {MASTER_REGULATOR}"
        )
