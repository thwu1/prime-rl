
import json
import os

import pytest

RESULTS_DIR = "/app/results"
QUERY_IDS = [f"R{i:02d}" for i in range(1, 11)]
TOL = 1e-4


def load_result(query_id):
    path = os.path.join(RESULTS_DIR, f"{query_id}.json")
    assert os.path.exists(path), f"Result file missing: {path}"
    with open(path) as f:
        return json.load(f)


def find_row(result, col_name, col_value):
    """Find a row by matching a column value; return dict of col->val."""
    idx = result["columns"].index(col_name)
    for row in result["rows"]:
        if row[idx] == col_value:
            return {result["columns"][i]: row[i] for i in range(len(result["columns"]))}
    return None


def get_col_values(result, col_name):
    """Get all values for a given column."""
    idx = result["columns"].index(col_name)
    return [row[idx] for row in result["rows"]]


# ── Structure ────────────────────────────────────────────────────────────────


class TestResultStructure:
    @pytest.mark.parametrize("qid", QUERY_IDS)
    def test_result_file_exists(self, qid):
        path = os.path.join(RESULTS_DIR, f"{qid}.json")
        assert os.path.exists(path), f"Missing result file for {qid}"

    @pytest.mark.parametrize("qid", QUERY_IDS)
    def test_result_format(self, qid):
        r = load_result(qid)
        assert r["query_id"] == qid
        assert isinstance(r["sql"], str) and len(r["sql"]) > 10
        assert isinstance(r["columns"], list) and len(r["columns"]) >= 1
        assert isinstance(r["rows"], list)

    @pytest.mark.parametrize("qid", QUERY_IDS)
    def test_sql_is_executable(self, qid):
        """The stored SQL must be syntactically valid."""
        import duckdb

        r = load_result(qid)
        conn = duckdb.connect("/app/insurance.duckdb", read_only=True)
        try:
            conn.execute(r["sql"])
        finally:
            conn.close()


# ── R01: total_premium by policy_number (simple aggregation) ─────────────


class TestR01:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R01")

    def test_row_count(self):
        assert len(self.r["rows"]) == 8

    def test_pol001(self):
        row = find_row(self.r, "policy_number", "POL-001")
        assert row is not None
        assert abs(row["total_premium"] - 12000.0) < TOL

    def test_pol003(self):
        row = find_row(self.r, "policy_number", "POL-003")
        assert row is not None
        assert abs(row["total_premium"] - 15000.0) < TOL

    def test_pol008(self):
        row = find_row(self.r, "policy_number", "POL-008")
        assert row is not None
        assert abs(row["total_premium"] - 7500.0) < TOL


# ── R02: claim_count (scalar) ────────────────────────────────────────────


class TestR02:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R02")

    def test_single_row(self):
        assert len(self.r["rows"]) == 1

    def test_claim_count_is_14(self):
        val = self.r["rows"][0][0]
        assert val == 14, f"Expected 14 claims, got {val}"


# ── R03: claim_count by party_name (multi-hop join + filter) ─────────────


class TestR03:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R03")

    def test_row_count(self):
        assert len(self.r["rows"]) == 3

    def test_alice(self):
        row = find_row(self.r, "party_name", "Alice Johnson")
        assert row is not None
        assert row["claim_count"] == 6

    def test_bob(self):
        row = find_row(self.r, "party_name", "Bob Smith")
        assert row is not None
        assert row["claim_count"] == 6

    def test_carol(self):
        row = find_row(self.r, "party_name", "Carol Davis")
        assert row is not None
        assert row["claim_count"] == 2


# ── R04: total_premium by catastrophe_name (FAN-OUT PREVENTION) ──────────


class TestR04FanOut:
    """Critical test: verifies fan-out prevention.

    Naive join (premium × claim per policy) inflates sums when a policy has
    multiple claims for the same catastrophe AND multiple premium rows.
    Correct implementation pre-aggregates premium per policy before bridging
    through DISTINCT (policy, catastrophe) pairs.
    """

    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R04")

    def test_row_count(self):
        assert len(self.r["rows"]) == 3

    def test_hurricane_alpha_correct(self):
        row = find_row(self.r, "catastrophe_name", "Hurricane Alpha")
        assert row is not None
        assert abs(row["total_premium"] - 36000.0) < TOL, (
            f"Hurricane Alpha premium should be 36000 (got {row['total_premium']}). "
            "If 48000, fan-out was not prevented."
        )

    def test_earthquake_beta_correct(self):
        row = find_row(self.r, "catastrophe_name", "Earthquake Beta")
        assert row is not None
        assert abs(row["total_premium"] - 26000.0) < TOL, (
            f"Earthquake Beta premium should be 26000 (got {row['total_premium']}). "
            "If 41000, fan-out was not prevented."
        )

    def test_flood_gamma_correct(self):
        row = find_row(self.r, "catastrophe_name", "Flood Gamma")
        assert row is not None
        assert abs(row["total_premium"] - 17500.0) < TOL


# ── R05: loss_ratio by policy_number (derived metric, cross-fact) ────────


class TestR05:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R05")

    def test_row_count(self):
        assert len(self.r["rows"]) == 8

    def test_pol001_loss_ratio(self):
        # total_incurred=18300, total_premium=12000 → 1.525
        row = find_row(self.r, "policy_number", "POL-001")
        assert row is not None
        assert abs(row["loss_ratio"] - 1.525) < TOL

    def test_pol003_loss_ratio(self):
        # total_incurred=30000, total_premium=15000 → 2.0
        row = find_row(self.r, "policy_number", "POL-003")
        assert row is not None
        assert abs(row["loss_ratio"] - 2.0) < TOL

    def test_pol005_loss_ratio(self):
        # total_incurred=5000, total_premium=6000 → 0.8333...
        row = find_row(self.r, "policy_number", "POL-005")
        assert row is not None
        assert abs(row["loss_ratio"] - 5000.0 / 6000.0) < TOL

    def test_pol004_loss_ratio(self):
        # total_incurred=55250, total_premium=10000 → 5.525
        row = find_row(self.r, "policy_number", "POL-004")
        assert row is not None
        assert abs(row["loss_ratio"] - 5.525) < TOL


# ── R06: total_loss_payment by policy_number, filtered (active only) ─────


class TestR06:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R06")

    def test_row_count(self):
        assert len(self.r["rows"]) == 6, (
            "Only 6 active policies have claims: POL-001,002,004,006,007,008"
        )

    def test_excludes_expired(self):
        row = find_row(self.r, "policy_number", "POL-003")
        assert row is None, "POL-003 is expired — should be excluded by filter"

    def test_excludes_cancelled(self):
        row = find_row(self.r, "policy_number", "POL-005")
        assert row is None, "POL-005 is cancelled — should be excluded by filter"

    def test_pol001_value(self):
        row = find_row(self.r, "policy_number", "POL-001")
        assert row is not None
        assert abs(row["total_loss_payment"] - 12500.0) < TOL

    def test_pol004_value(self):
        row = find_row(self.r, "policy_number", "POL-004")
        assert row is not None
        assert abs(row["total_loss_payment"] - 34000.0) < TOL


# ── R07: two metrics from same entity by claim_number ────────────────────


class TestR07:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R07")

    def test_row_count(self):
        assert len(self.r["rows"]) == 14

    def test_clm001(self):
        row = find_row(self.r, "claim_number", "CLM-001")
        assert row is not None
        assert abs(row["total_loss_payment"] - 5000.0) < TOL
        assert abs(row["total_loss_reserve"] - 2000.0) < TOL

    def test_clm006(self):
        row = find_row(self.r, "claim_number", "CLM-006")
        assert row is not None
        assert abs(row["total_loss_payment"] - 25000.0) < TOL
        assert abs(row["total_loss_reserve"] - 10000.0) < TOL

    def test_clm005_zero_reserve(self):
        row = find_row(self.r, "claim_number", "CLM-005")
        assert row is not None
        assert abs(row["total_loss_payment"] - 1500.0) < TOL
        assert abs(row["total_loss_reserve"] - 0.0) < TOL


# ── R08: multi-fact (premium + claim_count) by policy (FAN-OUT) ──────────


class TestR08MultiFact:
    """Verifies multi-fact composition with independent aggregation.

    Naive single-join approach inflates both metrics due to the cartesian
    product between premium rows and claim rows for the same policy.
    """

    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R08")

    def test_row_count(self):
        assert len(self.r["rows"]) == 8

    def test_pol001_premium_not_inflated(self):
        row = find_row(self.r, "policy_number", "POL-001")
        assert row is not None
        assert abs(row["total_premium"] - 12000.0) < TOL, (
            f"POL-001 premium should be 12000 (got {row['total_premium']}). "
            "If 48000, metrics were not independently aggregated."
        )

    def test_pol001_claim_count_not_inflated(self):
        row = find_row(self.r, "policy_number", "POL-001")
        assert row is not None
        assert row["claim_count"] == 4, (
            f"POL-001 claim_count should be 4 (got {row['claim_count']}). "
            "If 8, metrics were not independently aggregated."
        )

    def test_pol003(self):
        row = find_row(self.r, "policy_number", "POL-003")
        assert row is not None
        assert abs(row["total_premium"] - 15000.0) < TOL
        assert row["claim_count"] == 3

    def test_pol006(self):
        row = find_row(self.r, "policy_number", "POL-006")
        assert row is not None
        assert abs(row["total_premium"] - 9000.0) < TOL
        assert row["claim_count"] == 1


# ── R09: total_incurred (derived) by catastrophe_name ────────────────────


class TestR09:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R09")

    def test_row_count(self):
        assert len(self.r["rows"]) == 3

    def test_hurricane_alpha(self):
        row = find_row(self.r, "catastrophe_name", "Hurricane Alpha")
        assert row is not None
        assert abs(row["total_incurred"] - 42250.0) < TOL

    def test_earthquake_beta(self):
        row = find_row(self.r, "catastrophe_name", "Earthquake Beta")
        assert row is not None
        assert abs(row["total_incurred"] - 54000.0) < TOL

    def test_flood_gamma(self):
        row = find_row(self.r, "catastrophe_name", "Flood Gamma")
        assert row is not None
        assert abs(row["total_incurred"] - 50300.0) < TOL


# ── R10: avg_premium (derived + multi-hop + fan-out) by party_name ───────


class TestR10:
    @pytest.fixture(autouse=True)
    def result(self):
        self.r = load_result("R10")

    def test_row_count(self):
        assert len(self.r["rows"]) == 3

    def test_alice(self):
        # total_premium=31000, policy_count=3 → 10333.333...
        row = find_row(self.r, "party_name", "Alice Johnson")
        assert row is not None
        assert abs(row["avg_premium"] - 31000.0 / 3) < TOL

    def test_bob(self):
        # total_premium=32500, policy_count=3 → 10833.333...
        row = find_row(self.r, "party_name", "Bob Smith")
        assert row is not None
        assert abs(row["avg_premium"] - 32500.0 / 3) < TOL

    def test_carol(self):
        # total_premium=15000, policy_count=2 → 7500.0
        row = find_row(self.r, "party_name", "Carol Davis")
        assert row is not None
        assert abs(row["avg_premium"] - 7500.0) < TOL
