
import json
import os
import pytest

REPORT_PATH = "/app/impact_report.json"

EXPECTED_BASELINE = {
    "q01": "ALLOWED",
    "q02": "DENIED",
    "q03": "DENIED",
    "q04": "ALLOWED",
    "q05": "DENIED",
    "q06": "ALLOWED",
    "q07": "ALLOWED",
    "q08": "DENIED",
    "q09": "DENIED",
    "q10": "DENIED",
    "q11": "ALLOWED",
    "q12": "DENIED",
    "q13": "DENIED",
    "q14": "DENIED",
    "q15": "DENIED",
    "q16": "ALLOWED",
    "q17": "DENIED",
    "q18": "ALLOWED",
    "q19": "DENIED",
    "q20": "ALLOWED",
    "q21": "ALLOWED",
    "q22": "DENIED",
    "q23": "ALLOWED",
    "q24": "DENIED",
    "q25": "ALLOWED",
}

EXPECTED_CHANGES = {
    "change_01": {
        "classification": "OPENS_FORBIDDEN",
        "newly_allowed": ["q05"],
        "newly_denied": [],
    },
    "change_02": {
        "classification": "BREAKS_REQUIRED",
        "newly_allowed": [],
        "newly_denied": ["q07", "q16"],
    },
    "change_03": {
        "classification": "OPENS_FORBIDDEN",
        "newly_allowed": ["q19"],
        "newly_denied": [],
    },
    "change_04": {
        "classification": "BREAKS_REQUIRED",
        "newly_allowed": [],
        "newly_denied": ["q20", "q21", "q23"],
    },
    "change_05": {
        "classification": "SAFE",
        "newly_allowed": [],
        "newly_denied": [],
    },
    "change_06": {
        "classification": "CRITICAL",
        "newly_allowed": ["q05"],
        "newly_denied": ["q07", "q16"],
    },
}


class TestReportExists:
    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_PATH), (
            f"Impact report not found at {REPORT_PATH}"
        )


class TestReportStructure:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def test_has_baseline_key(self):
        assert "baseline" in self.report, "Report missing 'baseline' key"

    def test_has_changes_key(self):
        assert "changes" in self.report, "Report missing 'changes' key"

    def test_baseline_has_all_queries(self):
        for qid in EXPECTED_BASELINE:
            assert qid in self.report["baseline"], (
                f"Missing {qid} in baseline"
            )

    def test_changes_has_all_change_ids(self):
        for cid in EXPECTED_CHANGES:
            assert cid in self.report["changes"], (
                f"Missing {cid} in changes"
            )

    def test_change_entries_have_required_fields(self):
        for cid in EXPECTED_CHANGES:
            entry = self.report["changes"][cid]
            for field in ("classification", "newly_allowed", "newly_denied"):
                assert field in entry, f"{cid} missing '{field}' field"

    def test_baseline_verdicts_are_valid_values(self):
        for qid, verdict in self.report["baseline"].items():
            assert verdict in ("ALLOWED", "DENIED"), (
                f"Baseline {qid}: invalid verdict '{verdict}'"
            )

    def test_change_classifications_are_valid_values(self):
        valid = {"SAFE", "BREAKS_REQUIRED", "OPENS_FORBIDDEN", "CRITICAL"}
        for cid, entry in self.report["changes"].items():
            assert entry["classification"] in valid, (
                f"{cid}: invalid classification '{entry['classification']}'"
            )


class TestBaseline:
    """Verify each of the 25 baseline connectivity verdicts."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def _check(self, qid):
        expected = EXPECTED_BASELINE[qid]
        actual = self.report["baseline"].get(qid, "MISSING")
        assert actual == expected, (
            f"Baseline {qid}: expected {expected}, got {actual}"
        )

    def test_q01_frontend_to_orders_api_8080(self):
        self._check("q01")

    def test_q02_frontend_to_orders_api_9090(self):
        self._check("q02")

    def test_q03_frontend_to_postgres_5432(self):
        self._check("q03")

    def test_q04_orders_api_to_postgres_5432(self):
        self._check("q04")

    def test_q05_analytics_api_to_postgres_5432(self):
        self._check("q05")

    def test_q06_orders_api_to_redis_6379(self):
        self._check("q06")

    def test_q07_analytics_api_to_redis_6379(self):
        self._check("q07")

    def test_q08_postgres_to_orders_api_8080(self):
        self._check("q08")

    def test_q09_orders_api_to_frontend_80(self):
        self._check("q09")

    def test_q10_frontend_to_frontend_80(self):
        self._check("q10")

    def test_q11_users_api_to_postgres_5432(self):
        self._check("q11")

    def test_q12_orders_api_to_users_api_8080(self):
        self._check("q12")

    def test_q13_redis_to_postgres_5432(self):
        self._check("q13")

    def test_q14_orders_api_to_postgres_wrong_port(self):
        self._check("q14")

    def test_q15_frontend_to_redis_6379(self):
        self._check("q15")

    def test_q16_users_api_to_redis_6379(self):
        self._check("q16")

    def test_q17_postgres_to_redis_6379(self):
        self._check("q17")

    def test_q18_prometheus_to_grafana_3000(self):
        self._check("q18")

    def test_q19_prometheus_to_orders_api_8080(self):
        self._check("q19")

    def test_q20_orders_api_to_prometheus_9090(self):
        self._check("q20")

    def test_q21_users_api_to_prometheus_9090(self):
        self._check("q21")

    def test_q22_analytics_api_to_prometheus_9090(self):
        self._check("q22")

    def test_q23_orders_api_to_grafana_3000(self):
        self._check("q23")

    def test_q24_analytics_api_to_grafana_3000(self):
        self._check("q24")

    def test_q25_grafana_to_prometheus_9090(self):
        self._check("q25")


class TestChangeClassifications:
    """Verify the classification of each proposed change."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def _check_classification(self, cid):
        expected = EXPECTED_CHANGES[cid]["classification"]
        actual = self.report["changes"][cid]["classification"]
        assert actual == expected, (
            f"{cid}: expected classification '{expected}', got '{actual}'"
        )

    def test_change_01_relax_postgres_acl(self):
        self._check_classification("change_01")

    def test_change_02_restrict_redis_to_orders(self):
        self._check_classification("change_02")

    def test_change_03_allow_monitoring_scrape(self):
        self._check_classification("change_03")

    def test_change_04_remove_monitoring_egress(self):
        self._check_classification("change_04")

    def test_change_05_tighten_web_egress(self):
        self._check_classification("change_05")

    def test_change_06_compound_db_restructure(self):
        self._check_classification("change_06")


class TestChangeNewlyAllowed:
    """Verify newly_allowed lists for each proposed change."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def _check_newly_allowed(self, cid):
        expected = sorted(EXPECTED_CHANGES[cid]["newly_allowed"])
        actual = sorted(self.report["changes"][cid]["newly_allowed"])
        assert actual == expected, (
            f"{cid} newly_allowed: expected {expected}, got {actual}"
        )

    def test_change_01_newly_allowed(self):
        self._check_newly_allowed("change_01")

    def test_change_02_newly_allowed(self):
        self._check_newly_allowed("change_02")

    def test_change_03_newly_allowed(self):
        self._check_newly_allowed("change_03")

    def test_change_04_newly_allowed(self):
        self._check_newly_allowed("change_04")

    def test_change_05_newly_allowed(self):
        self._check_newly_allowed("change_05")

    def test_change_06_newly_allowed(self):
        self._check_newly_allowed("change_06")


class TestChangeNewlyDenied:
    """Verify newly_denied lists for each proposed change."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def _check_newly_denied(self, cid):
        expected = sorted(EXPECTED_CHANGES[cid]["newly_denied"])
        actual = sorted(self.report["changes"][cid]["newly_denied"])
        assert actual == expected, (
            f"{cid} newly_denied: expected {expected}, got {actual}"
        )

    def test_change_01_newly_denied(self):
        self._check_newly_denied("change_01")

    def test_change_02_newly_denied(self):
        self._check_newly_denied("change_02")

    def test_change_03_newly_denied(self):
        self._check_newly_denied("change_03")

    def test_change_04_newly_denied(self):
        self._check_newly_denied("change_04")

    def test_change_05_newly_denied(self):
        self._check_newly_denied("change_05")

    def test_change_06_newly_denied(self):
        self._check_newly_denied("change_06")
