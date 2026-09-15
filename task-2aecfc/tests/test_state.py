
import json
import os
import pytest


FINDINGS_PATH = "/app/output/findings.json"


@pytest.fixture(scope="module")
def findings():
    """Load the incident analysis findings produced by the solver."""
    assert os.path.isfile(FINDINGS_PATH), (
        f"Findings file not found at {FINDINGS_PATH}. "
        "The report must be written to /app/output/findings.json"
    )
    with open(FINDINGS_PATH) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Output schema integrity
# ---------------------------------------------------------------------------


def test_output_has_required_keys(findings):
    required = {
        "summary",
        "cluster_failures",
        "cascade_sequence",
        "alerts",
        "peak_error_rate",
        "peak_error_rate_time_s",
        "data_quality",
        "config_discrepancies",
    }
    assert required.issubset(findings.keys()), (
        f"Missing top-level keys: {required - findings.keys()}"
    )


def test_summary_has_required_keys(findings):
    required = {
        "total_requests",
        "total_errors",
        "overall_error_rate",
        "simulation_duration_s",
        "availability_budget_consumed_pct",
        "latency_sli",
        "latency_budget_consumed_pct",
    }
    assert required.issubset(findings["summary"].keys()), (
        f"Missing summary keys: {required - findings['summary'].keys()}"
    )


# ---------------------------------------------------------------------------
# Data quality evaluation — solver must discover and report duplicates
# ---------------------------------------------------------------------------


def test_data_quality_has_required_keys(findings):
    required = {
        "duplicates_found",
        "affected_cluster",
        "affected_time_range",
        "duplicate_rows_removed",
    }
    assert required.issubset(findings["data_quality"].keys()), (
        f"Missing data_quality keys: {required - findings['data_quality'].keys()}"
    )


def test_duplicates_detected(findings):
    """Solver must discover that the metrics DB contains duplicate entries."""
    assert findings["data_quality"]["duplicates_found"] is True


def test_duplicates_affected_cluster(findings):
    """Gamma cluster had a collector race condition causing double-ingestion."""
    assert findings["data_quality"]["affected_cluster"] == "gamma"


def test_duplicates_affected_time_range(findings):
    """Duplicates span the gamma incident window t=200 through t=229."""
    rng = findings["data_quality"]["affected_time_range"]
    assert rng[0] == 200
    assert rng[1] == 229


def test_duplicates_rows_removed(findings):
    """30 duplicate rows (one per second for gamma t=200-229)."""
    assert findings["data_quality"]["duplicate_rows_removed"] == 30


# ---------------------------------------------------------------------------
# Config discrepancy evaluation — solver must discover YAML merge key issue
# ---------------------------------------------------------------------------


def test_config_discrepancies_present(findings):
    """Solver must identify at least one configuration discrepancy."""
    assert len(findings["config_discrepancies"]) >= 1


def test_page_critical_burn_rate_discrepancy(findings):
    """page_critical has burn_rate=1.44 from YAML parse but should be 14.4."""
    pc = next(
        (d for d in findings["config_discrepancies"]
         if d["alert_name"] == "page_critical"),
        None,
    )
    assert pc is not None, "page_critical discrepancy must be reported"
    assert pc["field"] == "burn_rate"
    assert pc["parsed_value"] == pytest.approx(1.44, rel=1e-3)
    assert pc["intended_value"] == pytest.approx(14.4, rel=1e-3)


# ---------------------------------------------------------------------------
# Summary statistics — verifies data deduplication was applied
# ---------------------------------------------------------------------------


def test_total_requests_deduped(findings):
    """After deduplication, total requests must be 912000."""
    assert findings["summary"]["total_requests"] == 912000


def test_total_errors_deduped(findings):
    """After deduplication, total errors must be 40500."""
    assert findings["summary"]["total_errors"] == 40500


def test_overall_error_rate(findings):
    expected = 40500 / 912000
    assert findings["summary"]["overall_error_rate"] == pytest.approx(
        expected, rel=1e-3
    )


def test_simulation_duration(findings):
    assert findings["summary"]["simulation_duration_s"] == 600


def test_availability_budget_consumed(findings):
    """Availability error budget: burn_rate * (600 / 2592000) * 100."""
    expected = (40500 / 912000) / 0.001 * (600 / (30 * 86400)) * 100
    assert findings["summary"]["availability_budget_consumed_pct"] == pytest.approx(
        expected, rel=1e-2
    )


def test_availability_budget_not_inflated(findings):
    """Budget must be well below the ~77% value caused by time-unit errors."""
    assert findings["summary"]["availability_budget_consumed_pct"] < 5.0


# ---------------------------------------------------------------------------
# Latency SLI and error budget — multi-dimensional SLO analysis
# ---------------------------------------------------------------------------


def test_latency_sli_value(findings):
    """Latency SLI: 640000 compliant / 912000 total (request-weighted, p99<=200ms).

    Compliant: Phase1 all (400k), Phase2 alpha+beta (48k), Phase5 alpha (192k).
    Non-compliant: Phase2 gamma (12k), Phase3 alpha+beta (60k), Phase4 alpha (200k).
    """
    expected = 640000 / 912000
    assert findings["summary"]["latency_sli"] == pytest.approx(expected, rel=1e-3)


def test_latency_sli_below_one(findings):
    """Latency SLI must reflect significant violations during the incident."""
    assert findings["summary"]["latency_sli"] < 0.8


def test_latency_budget_consumed(findings):
    """Latency budget: (non_compliance_rate / (1-0.99)) * (600/2592000) * 100."""
    non_compliance = 272000 / 912000
    expected = (non_compliance / 0.01) * (600 / (30 * 86400)) * 100
    assert findings["summary"]["latency_budget_consumed_pct"] == pytest.approx(
        expected, rel=1e-2
    )


def test_latency_budget_reasonable_range(findings):
    """Latency budget should be < 5% for a 10-min window in a 30-day period."""
    assert 0.1 < findings["summary"]["latency_budget_consumed_pct"] < 5.0


# ---------------------------------------------------------------------------
# Cluster failure cascade detection
# ---------------------------------------------------------------------------


def test_cluster_failures_count(findings):
    assert len(findings["cluster_failures"]) == 2


def test_gamma_failure_timing(findings):
    """gamma: 360/400 = 90% error rate from t=200; detected after 30s at t=229."""
    gamma = next(
        (cf for cf in findings["cluster_failures"] if cf["cluster"] == "gamma"),
        None,
    )
    assert gamma is not None, "gamma must be in cluster_failures"
    assert gamma["detected_at_s"] == 229
    assert gamma["effective_from_s"] == 230


def test_beta_failure_timing(findings):
    """beta: 250/750 = 33% error rate from t=230; detected after 30s at t=259."""
    beta = next(
        (cf for cf in findings["cluster_failures"] if cf["cluster"] == "beta"),
        None,
    )
    assert beta is not None, "beta must be in cluster_failures"
    assert beta["detected_at_s"] == 259
    assert beta["effective_from_s"] == 260


def test_alpha_not_failed(findings):
    """alpha peak error rate 200/2000 = 10% never exceeds 25% threshold."""
    alpha = next(
        (cf for cf in findings["cluster_failures"] if cf["cluster"] == "alpha"),
        None,
    )
    assert alpha is None, "alpha must not appear in cluster_failures"


def test_cascade_sequence(findings):
    assert findings["cascade_sequence"] == ["gamma", "beta"]


# ---------------------------------------------------------------------------
# Multi-window multi-burn-rate alert evaluation
# ---------------------------------------------------------------------------


def test_alert_names_present(findings):
    alert_names = {a["name"] for a in findings["alerts"]}
    assert alert_names == {"ticket", "page_high", "page_critical"}


def test_ticket_fires_at_200(findings):
    """ticket (burn_rate=1.0, threshold=0.001) fires at t=200."""
    ticket = next(a for a in findings["alerts"] if a["name"] == "ticket")
    assert ticket["fired_at_s"] == 200


def test_page_high_fires_at_205(findings):
    """page_high (burn_rate=6.0, threshold=0.006) fires at t=205."""
    page_high = next(a for a in findings["alerts"] if a["name"] == "page_high")
    assert page_high["fired_at_s"] == 205


def test_page_critical_fires_at_216(findings):
    """page_critical with corrected burn_rate=14.4 fires at t=216."""
    page_critical = next(
        a for a in findings["alerts"] if a["name"] == "page_critical"
    )
    assert page_critical["fired_at_s"] == 216


def test_page_critical_not_at_200(findings):
    """Firing at t=200 indicates the YAML burn_rate discrepancy was not resolved."""
    page_critical = next(
        a for a in findings["alerts"] if a["name"] == "page_critical"
    )
    assert page_critical["fired_at_s"] != 200, (
        "page_critical firing at t=200 indicates burn_rate=1.44 was used "
        "instead of the intended 14.4 from the page severity default"
    )


def test_all_alerts_active_at_end(findings):
    for alert in findings["alerts"]:
        assert alert["active_at_end"] is True, (
            f"{alert['name']} should be active at end of simulation"
        )
        assert alert.get("resolved_at_s") is None, (
            f"{alert['name']} should have resolved_at_s = null"
        )


def test_alerts_sorted_by_fire_time(findings):
    fire_times = [
        a["fired_at_s"] for a in findings["alerts"] if a["fired_at_s"] is not None
    ]
    assert fire_times == sorted(fire_times)


# ---------------------------------------------------------------------------
# Peak error rate
# ---------------------------------------------------------------------------


def test_peak_error_rate_value(findings):
    """Peak per-second error rate after dedup: 362/2000 = 0.181."""
    expected = 362 / 2000
    assert findings["peak_error_rate"] == pytest.approx(expected, rel=1e-3)


def test_peak_error_rate_time(findings):
    assert findings["peak_error_rate_time_s"] == 200


def test_peak_error_rate_not_inflated(findings):
    """Peak rate must be below 0.20 (inflated with dupes would be ~0.30)."""
    assert findings["peak_error_rate"] < 0.20
