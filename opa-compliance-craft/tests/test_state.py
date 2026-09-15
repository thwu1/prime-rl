
import json
import subprocess
import os
import pytest


def _load_targets():
    with open("/app/target_outcomes.json") as f:
        return json.load(f)


def _run_opa_evaluation():
    """Run OPA evaluation and return a dict mapping PolicyId -> RequirementMet."""
    result = subprocess.run(
        [
            "opa", "eval", "data.aad.tests",
            "-i", "/app/tenant_input.json",
            "-d", "/app/rego/",
            "--format", "json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"OPA evaluation failed (rc={result.returncode}): {result.stderr}")
    output = json.loads(result.stdout)
    tests = output["result"][0]["expressions"][0]["value"]
    return {t["PolicyId"]: t["RequirementMet"] for t in tests}


# Module-level caches so OPA only runs once across all parametrized tests.
_OPA_RESULTS = None
_TARGETS = None


def get_opa_results():
    global _OPA_RESULTS
    if _OPA_RESULTS is None:
        _OPA_RESULTS = _run_opa_evaluation()
    return _OPA_RESULTS


def get_targets():
    global _TARGETS
    if _TARGETS is None:
        _TARGETS = _load_targets()
    return _TARGETS


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

def test_tenant_input_exists():
    assert os.path.exists("/app/tenant_input.json"), \
        "/app/tenant_input.json does not exist"


def test_tenant_input_is_valid_json():
    with open("/app/tenant_input.json") as f:
        data = json.load(f)
    assert isinstance(data, dict), "tenant_input.json must contain a JSON object"


def test_opa_evaluation_produces_results():
    results = get_opa_results()
    assert len(results) > 0, "OPA evaluation returned zero test results"


# ---------------------------------------------------------------------------
# Per-policy outcome checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "policy_id,expected",
    list(_load_targets().items()),
    ids=[pid for pid in _load_targets()],
)
def test_policy_outcome(policy_id, expected):
    results = get_opa_results()
    assert policy_id in results, \
        f"Policy {policy_id} not found in OPA evaluation output"
    actual = results[policy_id]
    assert actual == expected, (
        f"Policy {policy_id}: expected RequirementMet={expected}, got {actual}"
    )
