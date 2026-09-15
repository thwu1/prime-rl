
import json
import math
import os
import sqlite3
import pytest

RESULTS_PATH = "/app/results.json"
DB_PATH = "/app/data/acquisition.db"

# Ground truth generative parameters (NOT in the Docker image)
GROUND_TRUTH = {
    "organic":     {"c": 0.32, "scale": 45.0, "k": 1.3,  "cost": 0},
    "paid_search": {"c": 0.22, "scale": 30.0, "k": 0.85, "cost": 45},
    "social":      {"c": 0.12, "scale": 80.0, "k": 1.6,  "cost": 15},
    "referral":    {"c": 0.40, "scale": 20.0, "k": 1.0,  "cost": 25},
    "email":       {"c": 0.28, "scale": 35.0, "k": 0.75, "cost": 8},
}

EXPECTED_MEDIANS = {
    ch: gt["scale"] * math.log(2) ** (1.0 / gt["k"])
    for ch, gt in GROUND_TRUTH.items()
}

ALL_CHANNELS = sorted(GROUND_TRUTH.keys())
PAID_CHANNELS = sorted(
    ch for ch, gt in GROUND_TRUTH.items() if gt["cost"] > 0
)


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db_naive_rates():
    conn = sqlite3.connect(DB_PATH)
    rates = {}
    for row in conn.execute(
        "SELECT channel, conversion_rate FROM dashboard_metrics"
    ):
        rates[row[0]] = row[1]
    conn.close()
    return rates


# =====================================================================
# Structure tests
# =====================================================================
class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_has_methodology_flaw(self, results):
        assert "methodology_flaw" in results
        assert isinstance(results["methodology_flaw"], str)
        assert len(results["methodology_flaw"]) > 20

    def test_has_all_channels(self, results):
        assert "channels" in results
        for ch in ALL_CHANNELS:
            assert ch in results["channels"], f"Missing channel: {ch}"

    def test_channel_fields(self, results):
        required = [
            "naive_rate", "true_rate",
            "median_days_to_convert", "cost_per_true_conversion",
        ]
        for ch in ALL_CHANNELS:
            for field in required:
                assert field in results["channels"][ch], (
                    f"{ch}: missing field '{field}'"
                )

    def test_has_ranking(self, results):
        assert "ranking" in results
        assert isinstance(results["ranking"], list)
        assert set(results["ranking"]) == set(ALL_CHANNELS)

    def test_has_budget_allocation(self, results):
        assert "budget_allocation" in results
        assert isinstance(results["budget_allocation"], dict)


# =====================================================================
# Methodology flaw
# =====================================================================
class TestMethodologyFlaw:
    def test_identifies_core_issue(self, results):
        flaw = results["methodology_flaw"].lower()
        keywords = [
            "censor", "time", "bake", "bias", "observ", "window",
            "truncat", "recent", "mature", "incomplete", "premature",
            "insufficient", "haven't", "not yet", "survival",
            "right-censor", "observation period",
        ]
        assert any(k in flaw for k in keywords), (
            "Methodology flaw should reference censoring, observation time "
            f"bias, or similar concept. Got: {results['methodology_flaw']}"
        )


# =====================================================================
# Naive rates should match the database dashboard
# =====================================================================
class TestNaiveRates:
    @pytest.mark.parametrize("channel", ALL_CHANNELS)
    def test_naive_rate_matches_db(self, results, db_naive_rates, channel):
        reported = results["channels"][channel]["naive_rate"]
        expected = db_naive_rates[channel]
        assert abs(reported - expected) < 0.02, (
            f"{channel}: naive_rate={reported}, database={expected}"
        )


# =====================================================================
# True rates should be close to ground truth
# =====================================================================
class TestTrueRates:
    @pytest.mark.parametrize("channel", ALL_CHANNELS)
    def test_within_tolerance(self, results, channel):
        reported = results["channels"][channel]["true_rate"]
        gt_c = GROUND_TRUTH[channel]["c"]
        tolerance = max(0.05, gt_c * 0.25)
        assert abs(reported - gt_c) < tolerance, (
            f"{channel}: true_rate={reported:.4f}, ground_truth={gt_c}, "
            f"tolerance={tolerance:.4f}"
        )

    @pytest.mark.parametrize("channel", ALL_CHANNELS)
    def test_exceeds_naive(self, results, channel):
        true_r = results["channels"][channel]["true_rate"]
        naive_r = results["channels"][channel]["naive_rate"]
        assert true_r > naive_r - 0.005, (
            f"{channel}: true_rate ({true_r:.4f}) should exceed "
            f"naive_rate ({naive_r:.4f})"
        )

    def test_referral_highest(self, results):
        rates = {
            ch: results["channels"][ch]["true_rate"] for ch in ALL_CHANNELS
        }
        assert rates["referral"] > rates["organic"], (
            "referral should have highest true conversion rate"
        )

    def test_social_lowest(self, results):
        rates = {
            ch: results["channels"][ch]["true_rate"] for ch in ALL_CHANNELS
        }
        assert rates["social"] < rates["paid_search"], (
            "social should have lowest true conversion rate"
        )


# =====================================================================
# Median days to convert
# =====================================================================
class TestMedianDays:
    @pytest.mark.parametrize("channel", ALL_CHANNELS)
    def test_reasonable_range(self, results, channel):
        reported = results["channels"][channel]["median_days_to_convert"]
        expected = EXPECTED_MEDIANS[channel]
        rel_err = abs(reported - expected) / expected
        assert rel_err < 0.40, (
            f"{channel}: median_days={reported:.1f}, "
            f"expected~={expected:.1f}, rel_err={rel_err:.3f}"
        )

    @pytest.mark.parametrize("channel", ALL_CHANNELS)
    def test_positive(self, results, channel):
        assert results["channels"][channel]["median_days_to_convert"] > 0

    def test_social_slowest(self, results):
        medians = {
            ch: results["channels"][ch]["median_days_to_convert"]
            for ch in ALL_CHANNELS
        }
        assert medians["social"] > medians["referral"], (
            "social should have longest median conversion time"
        )


# =====================================================================
# Cost per true conversion
# =====================================================================
class TestCostPerConversion:
    def test_organic_free(self, results):
        cpc = results["channels"]["organic"]["cost_per_true_conversion"]
        assert cpc is None or cpc == 0, (
            f"organic should have null/zero cost, got {cpc}"
        )

    @pytest.mark.parametrize("channel", PAID_CHANNELS)
    def test_paid_positive(self, results, channel):
        cpc = results["channels"][channel]["cost_per_true_conversion"]
        assert cpc is not None and cpc > 0, (
            f"{channel}: expected positive cost_per_true_conversion"
        )

    def test_email_cheapest_paid(self, results):
        costs = {}
        for ch in PAID_CHANNELS:
            cpc = results["channels"][ch]["cost_per_true_conversion"]
            if cpc is not None:
                costs[ch] = cpc
        email_cost = costs["email"]
        for ch, cost in costs.items():
            if ch != "email":
                assert email_cost < cost, (
                    f"email (${email_cost:.2f}) should be cheapest paid, "
                    f"but {ch} costs ${cost:.2f}"
                )

    def test_paid_search_most_expensive(self, results):
        costs = {}
        for ch in PAID_CHANNELS:
            cpc = results["channels"][ch]["cost_per_true_conversion"]
            if cpc is not None:
                costs[ch] = cpc
        ps_cost = costs["paid_search"]
        for ch, cost in costs.items():
            if ch != "paid_search":
                assert ps_cost > cost, (
                    f"paid_search (${ps_cost:.2f}) should be most expensive, "
                    f"but {ch} costs ${cost:.2f}"
                )


# =====================================================================
# Ranking
# =====================================================================
class TestRanking:
    def test_organic_first(self, results):
        assert results["ranking"][0] == "organic", (
            f"Free channel (organic) should be first, "
            f"got {results['ranking'][0]}"
        )

    def test_email_second(self, results):
        ranking = results["ranking"]
        paid_rank = [ch for ch in ranking if ch != "organic"]
        assert paid_rank[0] == "email", (
            f"email should be most cost-effective paid channel, "
            f"got {paid_rank[0]}"
        )

    def test_paid_search_last(self, results):
        assert results["ranking"][-1] == "paid_search", (
            f"paid_search should be least cost-effective, "
            f"got {results['ranking'][-1]}"
        )


# =====================================================================
# Budget allocation
# =====================================================================
class TestBudgetAllocation:
    def test_excludes_organic(self, results):
        alloc = results["budget_allocation"]
        assert "organic" not in alloc, (
            "organic (free) should not be in budget allocation"
        )

    def test_includes_all_paid(self, results):
        alloc = results["budget_allocation"]
        for ch in PAID_CHANNELS:
            assert ch in alloc, f"Missing {ch} from budget allocation"

    def test_sums_to_one(self, results):
        total = sum(results["budget_allocation"].values())
        assert 0.90 < total < 1.10, (
            f"Budget allocation sums to {total:.3f}, expected ~1.0"
        )

    def test_all_positive(self, results):
        for ch, share in results["budget_allocation"].items():
            assert share > 0, f"{ch}: budget share should be positive"

    def test_email_gets_most(self, results):
        alloc = results["budget_allocation"]
        email_share = alloc.get("email", 0)
        for ch, share in alloc.items():
            if ch != "email":
                assert email_share >= share - 0.01, (
                    f"email ({email_share:.3f}) should get most budget, "
                    f"but {ch} gets {share:.3f}"
                )
