
import json
import os
import pytest


EXPECTED_VERDICTS = {
    "Q01": "ALLOWED",
    "Q02": "DENIED",
    "Q03": "ALLOWED",
    "Q04": "DENIED",
    "Q05": "ALLOWED",
    "Q06": "DENIED",
    "Q07": "ALLOWED",
    "Q08": "ALLOWED",
    "Q09": "DENIED",
    "Q10": "ALLOWED",
    "Q11": "DENIED",
    "Q12": "DENIED",
    "Q13": "ALLOWED",
    "Q14": "DENIED",
    "Q15": "ALLOWED",
    "Q16": "ALLOWED",
    "Q17": "DENIED",
    "Q18": "DENIED",
}


@pytest.fixture
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), f"Results file not found at {results_path}"
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, list), "results.json must be a JSON array"
    return {r["id"]: r for r in data}


def test_results_file_exists():
    assert os.path.exists("/app/results.json"), "results.json must exist at /app/results.json"


def test_results_has_all_queries(results):
    for qid in EXPECTED_VERDICTS:
        assert qid in results, f"Missing query {qid} in results"


def test_results_count(results):
    assert len(results) == len(EXPECTED_VERDICTS), (
        f"Expected {len(EXPECTED_VERDICTS)} results, got {len(results)}"
    )


def test_result_fields(results):
    required_fields = {"id", "from", "to", "port", "protocol", "verdict"}
    for qid, result in results.items():
        for field in required_fields:
            assert field in result, f"Query {qid} missing field '{field}'"


@pytest.mark.parametrize("query_id,expected", list(EXPECTED_VERDICTS.items()))
def test_verdict(results, query_id, expected):
    assert query_id in results, f"Query {query_id} not found in results"
    actual = results[query_id]["verdict"]
    assert actual == expected, (
        f"Query {query_id} ({results[query_id]['from']} -> {results[query_id]['to']} "
        f"{results[query_id]['protocol']}/{results[query_id]['port']}): "
        f"expected {expected}, got {actual}"
    )


def test_q06_default_deny_override(results):
    """Cache has enableDefaultDeny.ingress=false in one policy, but another
    policy's implicit default-deny overrides it. Frontend is not app=backend
    so it gets no allow match."""
    assert results["Q06"]["verdict"] == "DENIED"


def test_q15_ccnp_egress_and_ingress(results):
    """Monitoring egress restricted by CCNP to 10.0.0.0/8 (frontend is in range).
    Frontend ingress default-deny is ON from CCNP cross-env-deny, but CCNP
    node-exporter-access allows monitoring on port 9100."""
    assert results["Q15"]["verdict"] == "ALLOWED"


def test_q17_ccnp_cross_env_deny(results):
    """CCNP global-cross-env-deny blocks staging endpoints from reaching
    prod endpoints on port 443. staging-fe has env=staging, frontend has
    env=prod."""
    assert results["Q17"]["verdict"] == "DENIED"


def test_q18_monitoring_egress_allowed_but_ingress_denied(results):
    """Monitoring can egress to database (CCNP ops egress allows 10.0.0.0/8),
    but database ingress only allows backend on 5432 and monitoring on 5432.
    Port 443 has no ingress allow rule for monitoring."""
    assert results["Q18"]["verdict"] == "DENIED"


def test_q05_monitoring_egress_with_ccnp(results):
    """After CCNP ops egress restrict, monitoring has egress default-deny ON.
    But toCIDR 10.0.0.0/8 allows it, and database ingress allows monitoring
    on port 5432."""
    assert results["Q05"]["verdict"] == "ALLOWED"
