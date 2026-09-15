
import json
import os
import pytest

OUTPUT = "/app/output"
TOL = 1e-4


def load(name):
    path = os.path.join(OUTPUT, name)
    assert os.path.isfile(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Root scores
# ---------------------------------------------------------------------------

class TestScores:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load("scores.json")

    def test_alpha_judge1(self):
        assert abs(self.data["alpha/alpha_judge1"] - 199 / 360) < TOL

    def test_alpha_judge2(self):
        assert abs(self.data["alpha/alpha_judge2"] - 229 / 360) < TOL

    def test_alpha_ground_truth(self):
        assert abs(self.data["alpha/alpha_ground_truth"] - 0.85) < TOL

    def test_beta_judge1(self):
        assert abs(self.data["beta/beta_judge1"] - 0.6) < TOL

    def test_gamma_judge1(self):
        assert abs(self.data["gamma/gamma_judge1"] - 352 / 567) < TOL

    def test_gamma_judge2(self):
        assert abs(self.data["gamma/gamma_judge2"] - 1247 / 2268) < TOL

    def test_has_six_entries(self):
        assert len(self.data) == 6


# ---------------------------------------------------------------------------
# Sensitivity (effective weights)
# ---------------------------------------------------------------------------

class TestSensitivity:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load("sensitivity.json")

    def test_alpha_sum_to_one(self):
        total = sum(self.data["alpha"].values())
        assert abs(total - 1.0) < TOL

    def test_beta_sum_to_one(self):
        total = sum(self.data["beta"].values())
        assert abs(total - 1.0) < TOL

    def test_gamma_sum_to_one(self):
        total = sum(self.data["gamma"].values())
        assert abs(total - 1.0) < TOL

    def test_alpha_specific_weights(self):
        a = self.data["alpha"]
        assert abs(a["deps-installed"] - 0.1) < TOL
        assert abs(a["encoder"] - 0.1) < TOL
        assert abs(a["decoder"] - 0.1) < TOL
        assert abs(a["table1-match"] - 0.1) < TOL
        assert abs(a["data-loaded"] - 1 / 15) < TOL
        assert abs(a["forward-pass"] - 1 / 18) < TOL
        assert abs(a["attention"] - 0.05) < TOL
        assert abs(a["config-valid"] - 1 / 30) < TOL

    def test_beta_specific_weights(self):
        b = self.data["beta"]
        assert abs(b["algo-core"] - 0.4) < TOL
        assert abs(b["algo-ext"] - 0.2) < TOL
        assert abs(b["exp-run"] - 0.2) < TOL
        assert abs(b["exp-match"] - 0.2) < TOL

    def test_gamma_specific_weights(self):
        g = self.data["gamma"]
        assert abs(g["architecture"] - 5 / 63) < TOL
        assert abs(g["design-correct"] - 5 / 63) < TOL
        assert abs(g["readme"] - 2 / 27) < TOL
        assert abs(g["table-match"] - 1 / 18) < TOL
        assert abs(g["training-runs"] - 4 / 81) < TOL
        assert abs(g["ablation-runs"] - 2 / 81) < TOL
        assert abs(g["citations-valid"] - 5 / 378) < TOL

    def test_alpha_ordering(self):
        vals = list(self.data["alpha"].values())
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1] - TOL

    def test_gamma_ordering(self):
        vals = list(self.data["gamma"].values())
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1] - TOL

    def test_gamma_leaf_count(self):
        assert len(self.data["gamma"]) == 25


# ---------------------------------------------------------------------------
# Category analysis
# ---------------------------------------------------------------------------

class TestCategories:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load("categories.json")

    def test_alpha_judge1(self):
        c = self.data["alpha/alpha_judge1"]
        assert abs(c["Code Development"] - 161 / 197) < TOL
        assert abs(c["Execution"] - 38 / 73) < TOL
        assert abs(c["Result Match"] - 0.0) < TOL

    def test_alpha_judge2(self):
        c = self.data["alpha/alpha_judge2"]
        assert abs(c["Code Development"] - 140 / 197) < TOL
        assert abs(c["Execution"] - 35 / 73) < TOL
        assert abs(c["Result Match"] - 0.6) < TOL

    def test_alpha_ground_truth(self):
        c = self.data["alpha/alpha_ground_truth"]
        assert abs(c["Code Development"] - 1.0) < TOL
        assert abs(c["Execution"] - 1.0) < TOL
        assert abs(c["Result Match"] - 0.4) < TOL

    def test_beta_judge1(self):
        c = self.data["beta/beta_judge1"]
        assert abs(c["Code Development"] - 2 / 3) < TOL
        assert abs(c["Execution"] - 1.0) < TOL
        assert abs(c["Result Match"] - 0.0) < TOL

    def test_gamma_judge1(self):
        c = self.data["gamma/gamma_judge1"]
        assert abs(c["Code Development"] - 47 / 63) < TOL
        assert abs(c["Execution"] - 5 / 9) < TOL
        assert abs(c["Result Match"] - 0.0) < TOL

    def test_gamma_judge2(self):
        c = self.data["gamma/gamma_judge2"]
        assert abs(c["Code Development"] - 139 / 252) < TOL
        assert abs(c["Execution"] - 4 / 9) < TOL
        assert abs(c["Result Match"] - 0.75) < TOL

    def test_has_six_entries(self):
        assert len(self.data) == 6


# ---------------------------------------------------------------------------
# Agreement metrics (weighted per scoring policy)
# ---------------------------------------------------------------------------

class TestAgreement:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load("agreement.json")

    def test_alpha_j1_vs_j2(self):
        a = self.data["alpha_j1_vs_j2"]
        assert abs(a["cohens_kappa"] - (-8131 / 31469)) < TOL
        assert abs(a["accuracy"] - 7 / 18) < TOL
        assert abs(a["precision"] - 104 / 199) < TOL
        assert abs(a["recall"] - 104 / 229) < TOL
        assert abs(a["f1"] - 52 / 107) < TOL

    def test_alpha_j1_vs_gt(self):
        a = self.data["alpha_j1_vs_gt"]
        assert abs(a["cohens_kappa"] - 597 / 1667) < TOL
        assert abs(a["accuracy"] - 253 / 360) < TOL
        assert abs(a["precision"] - 1.0) < TOL
        assert abs(a["recall"] - 199 / 306) < TOL
        assert abs(a["f1"] - 398 / 505) < TOL

    def test_gamma_j1_vs_j2(self):
        a = self.data["gamma_j1_vs_j2"]
        assert abs(a["cohens_kappa"] - (-28276 / 48269)) < TOL
        assert abs(a["accuracy"] - 19 / 84) < TOL
        assert abs(a["precision"] - 225 / 704) < TOL
        assert abs(a["recall"] - 450 / 1247) < TOL
        assert abs(a["f1"] - 20 / 59) < TOL

    def test_has_three_pairs(self):
        assert len(self.data) == 3


# ---------------------------------------------------------------------------
# Improvements
# ---------------------------------------------------------------------------

class TestImprovements:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load("improvements.json")

    def test_alpha_judge1(self):
        d = self.data["alpha/alpha_judge1"]
        assert d["top_leaves"] == ["decoder", "table1-match", "table2-match"]
        assert abs(d["improved_score"] - 307 / 360) < TOL

    def test_alpha_judge2(self):
        d = self.data["alpha/alpha_judge2"]
        assert d["top_leaves"] == ["table2-match", "data-loaded", "forward-pass"]
        assert abs(d["improved_score"] - 309 / 360) < TOL

    def test_alpha_ground_truth(self):
        d = self.data["alpha/alpha_ground_truth"]
        assert set(d["top_leaves"]) == {"table2-match", "figure1-match"}
        assert len(d["top_leaves"]) == 2
        assert abs(d["improved_score"] - 1.0) < TOL

    def test_beta_judge1(self):
        d = self.data["beta/beta_judge1"]
        assert set(d["top_leaves"]) == {"algo-ext", "exp-match"}
        assert len(d["top_leaves"]) == 2
        assert abs(d["improved_score"] - 1.0) < TOL

    def test_gamma_judge1(self):
        d = self.data["gamma/gamma_judge1"]
        assert d["top_leaves"] == ["table-match", "loss-function", "api-docs"]
        assert abs(d["improved_score"] - 869 / 1134) < TOL

    def test_gamma_judge2(self):
        d = self.data["gamma/gamma_judge2"]
        assert d["top_leaves"] == ["design-correct", "readme", "training-runs"]
        assert abs(d["improved_score"] - 569 / 756) < TOL

    def test_has_six_entries(self):
        assert len(self.data) == 6
