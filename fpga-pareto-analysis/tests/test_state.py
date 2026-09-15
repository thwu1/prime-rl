
import json
import os
import pytest

RESULTS_DIR = "/app/results"


def load_json(filename):
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


# ---- summary.json tests ----

class TestSummary:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("summary.json")

    def test_all_llms_present(self):
        expected_llms = {
            "gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-o1-mini",
            "llama3.1-405B", "qwen-max", "qwen-plus",
            "qwen2.5-coder-32B-instruct", "codestral"
        }
        assert set(self.data.keys()) == expected_llms

    def test_total_solutions_per_llm(self):
        for llm in self.data:
            assert self.data[llm]["total_solutions"] == 840, \
                f"{llm} should have 840 total solutions"

    def test_passing_solutions_counts(self):
        expected = {
            "gpt-3.5-turbo": 362,
            "gpt-4": 542,
            "gpt-4o": 619,
            "gpt-o1-mini": 631,
            "llama3.1-405B": 460,
            "qwen-max": 535,
            "qwen-plus": 425,
            "qwen2.5-coder-32B-instruct": 505,
            "codestral": 542,
        }
        for llm, expected_count in expected.items():
            assert self.data[llm]["passing_solutions"] == expected_count, \
                f"{llm} passing_solutions: expected {expected_count}, got {self.data[llm]['passing_solutions']}"

    def test_passing_with_resources_counts(self):
        expected = {
            "gpt-3.5-turbo": 349,
            "gpt-4": 536,
            "gpt-4o": 616,
            "gpt-o1-mini": 622,
            "llama3.1-405B": 456,
            "qwen-max": 517,
            "qwen-plus": 404,
            "qwen2.5-coder-32B-instruct": 503,
            "codestral": 540,
        }
        for llm, expected_count in expected.items():
            assert self.data[llm]["passing_with_resources"] == expected_count, \
                f"{llm} passing_with_resources: expected {expected_count}, got {self.data[llm]['passing_with_resources']}"

    def test_pass_rates(self):
        expected = {
            "gpt-3.5-turbo": 43.1,
            "gpt-4o": 73.69,
            "gpt-o1-mini": 75.12,
        }
        for llm, expected_rate in expected.items():
            assert abs(self.data[llm]["pass_rate"] - expected_rate) < 0.05, \
                f"{llm} pass_rate: expected {expected_rate}, got {self.data[llm]['pass_rate']}"

    def test_avg_weighted_cost_gpt4o(self):
        cost = self.data["gpt-4o"]["avg_weighted_cost"]
        assert abs(cost - 3038.18) < 1.0, \
            f"gpt-4o avg_weighted_cost: expected ~3038.18, got {cost}"

    def test_avg_weighted_cost_gpt35(self):
        cost = self.data["gpt-3.5-turbo"]["avg_weighted_cost"]
        assert abs(cost - 2872.66) < 1.0, \
            f"gpt-3.5-turbo avg_weighted_cost: expected ~2872.66, got {cost}"

    def test_category_pass_rates(self):
        cats = self.data["gpt-4o"]["categories"]
        assert abs(cats["Combinational Logic"]["pass_rate"] - 100.0) < 0.05
        assert abs(cats["Bitwise and Logical Operations"]["pass_rate"] - 96.67) < 0.05
        assert abs(cats["Pipelining"]["pass_rate"] - 34.67) < 0.05

    def test_category_pass_rates_o1mini(self):
        cats = self.data["gpt-o1-mini"]["categories"]
        assert abs(cats["Machine Learning"]["pass_rate"] - 97.33) < 0.05
        assert abs(cats["Financial Computing"]["pass_rate"] - 33.33) < 0.05

    def test_has_category_avg_cost(self):
        cats = self.data["gpt-4o"]["categories"]
        for cat_name, cat_data in cats.items():
            assert "avg_weighted_cost" in cat_data, \
                f"Missing avg_weighted_cost for {cat_name}"


# ---- pareto_fronts.json tests ----

class TestParetoFronts:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("pareto_fronts.json")

    def test_parity_8bit_single_pareto(self):
        pts = self.data["parity_8bit"]
        assert len(pts) == 1
        p = pts[0]
        assert p["LUT"] == 2
        assert p["FF"] == 0
        assert p["DSP"] == 0
        assert p["BRAM"] == 0
        assert abs(p["weighted_cost"] - 3.8) < 0.01

    def test_mux4to1_single_pareto(self):
        pts = self.data["mux4to1"]
        assert len(pts) == 1
        assert pts[0]["LUT"] == 1
        assert pts[0]["FF"] == 0
        assert pts[0]["DSP"] == 0
        assert pts[0]["BRAM"] == 0

    def test_int_sqrt_two_pareto(self):
        pts = self.data["int_sqrt"]
        assert len(pts) == 2
        resource_vecs = {(p["LUT"], p["FF"], p["DSP"], p["BRAM"]) for p in pts}
        assert (159, 0, 0, 0) in resource_vecs
        assert (64, 0, 7, 0) in resource_vecs

    def test_polynomial_2_four_pareto(self):
        pts = self.data["polynomial_2"]
        assert len(pts) == 4
        resource_vecs = {(p["LUT"], p["FF"], p["DSP"], p["BRAM"]) for p in pts}
        assert (49, 0, 3, 0) in resource_vecs
        assert (0, 0, 4, 0) in resource_vecs
        assert (97, 0, 1, 0) in resource_vecs
        assert (83, 0, 2, 0) in resource_vecs

    def test_heat_index_three_pareto(self):
        pts = self.data["heat_index"]
        assert len(pts) == 3
        resource_vecs = {(p["LUT"], p["FF"], p["DSP"], p["BRAM"]) for p in pts}
        assert (16, 0, 18, 0) in resource_vecs
        assert (175, 0, 11, 0) in resource_vecs
        assert (124, 0, 12, 0) in resource_vecs

    def test_fsm_3state_two_pareto(self):
        pts = self.data["fsm_3state"]
        assert len(pts) == 2
        resource_vecs = {(p["LUT"], p["FF"], p["DSP"], p["BRAM"]) for p in pts}
        assert (1, 2, 0, 0) in resource_vecs
        assert (0, 3, 0, 0) in resource_vecs

    def test_pareto_points_are_nondominated(self):
        for module, pts in self.data.items():
            for i, a in enumerate(pts):
                for j, b in enumerate(pts):
                    if i == j:
                        continue
                    all_le = (
                        a["LUT"] <= b["LUT"]
                        and a["FF"] <= b["FF"]
                        and a["DSP"] <= b["DSP"]
                        and a["BRAM"] <= b["BRAM"]
                    )
                    any_lt = (
                        a["LUT"] < b["LUT"]
                        or a["FF"] < b["FF"]
                        or a["DSP"] < b["DSP"]
                        or a["BRAM"] < b["BRAM"]
                    )
                    assert not (all_le and any_lt), \
                        f"In {module}: point {a} dominates {b}"

    def test_weighted_cost_correct(self):
        for module, pts in self.data.items():
            for p in pts:
                expected = 1.0 * p["LUT"] + 0.5 * p["FF"] + 10.0 * p["DSP"] + 20.0 * p["BRAM"]
                assert p["weighted_cost"] >= expected - 0.01, \
                    f"In {module}: cost {p['weighted_cost']} < expected minimum {expected}"

    def test_modules_with_multi_pareto(self):
        multi = [m for m, pts in self.data.items() if len(pts) > 1]
        assert len(multi) == 9, \
            f"Expected 9 modules with >1 Pareto point, got {len(multi)}: {multi}"

    def test_total_modules_with_data(self):
        assert len(self.data) == 54, \
            f"Expected 54 modules, got {len(self.data)}"

    def test_sorted_by_cost(self):
        for module, pts in self.data.items():
            costs = [p["weighted_cost"] for p in pts]
            assert costs == sorted(costs), \
                f"{module}: Pareto points not sorted by weighted cost"


# ---- hypervolumes.json tests ----

class TestHypervolumes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("hypervolumes.json")

    def test_int_sqrt_hypervolume(self):
        hv = self.data["int_sqrt"]
        assert hv["num_pareto_points"] == 2
        assert abs(hv["hypervolume"] - 103.0) < 0.01, \
            f"int_sqrt HV: expected 103, got {hv['hypervolume']}"
        assert hv["reference_point"] == [160, 1, 8]

    def test_polynomial_2_hypervolume(self):
        hv = self.data["polynomial_2"]
        assert hv["num_pareto_points"] == 4
        assert abs(hv["hypervolume"] - 163.0) < 0.01, \
            f"polynomial_2 HV: expected 163, got {hv['hypervolume']}"
        assert hv["reference_point"] == [98, 1, 5]

    def test_heat_index_hypervolume(self):
        hv = self.data["heat_index"]
        assert hv["num_pareto_points"] == 3
        assert abs(hv["hypervolume"] - 473.0) < 0.01, \
            f"heat_index HV: expected 473, got {hv['hypervolume']}"
        assert hv["reference_point"] == [176, 1, 19]

    def test_fsm_3state_hypervolume(self):
        hv = self.data["fsm_3state"]
        assert hv["num_pareto_points"] == 2
        assert abs(hv["hypervolume"] - 3.0) < 0.01, \
            f"fsm_3state HV: expected 3, got {hv['hypervolume']}"
        assert hv["reference_point"] == [2, 4, 1]

    def test_polynomial_4_hypervolume(self):
        hv = self.data["polynomial_4"]
        assert hv["num_pareto_points"] == 3
        assert abs(hv["hypervolume"] - 164.0) < 0.01, \
            f"polynomial_4 HV: expected 164, got {hv['hypervolume']}"

    def test_total_modules_in_hypervolumes(self):
        assert len(self.data) == 54, \
            f"Expected 54 modules, got {len(self.data)}"

    def test_all_hypervolumes_nonnegative(self):
        for module, hv in self.data.items():
            assert hv["hypervolume"] >= 0, \
                f"{module}: hypervolume should be >= 0"


# ---- rankings.json tests ----

class TestRankings:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("rankings.json")

    def test_all_llms_present(self):
        expected = {
            "gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-o1-mini",
            "llama3.1-405B", "qwen-max", "qwen-plus",
            "qwen2.5-coder-32B-instruct", "codestral"
        }
        assert set(self.data.keys()) == expected

    def test_max_is_one(self):
        assert abs(max(self.data.values()) - 1.0) < 1e-6

    def test_all_positive(self):
        for llm, score in self.data.items():
            assert 0 < score <= 1.0, f"{llm}: score {score} out of range"

    def test_top_ranked_is_o1_mini(self):
        top = max(self.data, key=self.data.get)
        assert top == "gpt-o1-mini", \
            f"Expected gpt-o1-mini at top, got {top}"
        assert abs(self.data["gpt-o1-mini"] - 1.0) < 1e-6

    def test_ranking_order(self):
        sorted_llms = sorted(self.data, key=self.data.get, reverse=True)
        assert sorted_llms[0] == "gpt-o1-mini"
        assert sorted_llms[1] == "gpt-4"
        assert sorted_llms[2] == "codestral"

    def test_bottom_two(self):
        sorted_llms = sorted(self.data, key=self.data.get, reverse=True)
        bottom_two = set(sorted_llms[-2:])
        assert bottom_two == {"qwen-plus", "gpt-3.5-turbo"}, \
            f"Expected bottom 2 to be qwen-plus and gpt-3.5-turbo, got {bottom_two}"

    def test_specific_values(self):
        assert abs(self.data["gpt-4"] - 0.8879) < 0.005, \
            f"gpt-4 ranking: expected ~0.8879, got {self.data['gpt-4']}"
        assert abs(self.data["codestral"] - 0.8813) < 0.005, \
            f"codestral ranking: expected ~0.8813, got {self.data['codestral']}"

    def test_gpt4o_value(self):
        assert abs(self.data["gpt-4o"] - 0.8701) < 0.005, \
            f"gpt-4o ranking: expected ~0.8701, got {self.data['gpt-4o']}"


# ---- correlations.json tests ----

class TestCorrelations:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("correlations.json")

    def test_correct_number_of_pairs(self):
        assert len(self.data) == 36, \
            f"Expected 36 pairs, got {len(self.data)}"

    def test_lexicographic_key_order(self):
        for key in self.data:
            parts = key.split("|")
            assert len(parts) == 2, f"Key format wrong: {key}"
            assert parts[0] < parts[1], \
                f"Key not in lex order: {key}"

    def test_values_in_range(self):
        for key, tau in self.data.items():
            assert -1.0 <= tau <= 1.0, \
                f"Kendall's tau out of range for {key}: {tau}"

    def test_gpt4o_vs_o1mini(self):
        tau = self.data["gpt-4o|gpt-o1-mini"]
        assert abs(tau - 0.8263) < 0.02, \
            f"gpt-4o|gpt-o1-mini: expected ~0.8263, got {tau}"

    def test_gpt35_vs_gpt4(self):
        tau = self.data["gpt-3.5-turbo|gpt-4"]
        assert abs(tau - 0.9746) < 0.02, \
            f"gpt-3.5-turbo|gpt-4: expected ~0.9746, got {tau}"

    def test_codestral_vs_llama(self):
        tau = self.data["codestral|llama3.1-405B"]
        assert abs(tau - 0.9494) < 0.02, \
            f"codestral|llama3.1-405B: expected ~0.9494, got {tau}"

    def test_all_correlations_high(self):
        for key, tau in self.data.items():
            assert tau > 0.3, \
                f"Unexpectedly low correlation for {key}: {tau}"
