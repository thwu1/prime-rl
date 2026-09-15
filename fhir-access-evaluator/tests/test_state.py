"""
Tests for FHIR AccessPolicy Evaluation Audit Pipeline.

Runs /app/run_pipeline.sh and validates:
- /app/results.json: access decisions for 35 scenarios
- /app/audit.json: HMAC-SHA256 audit signatures

Covers: interaction restrictions, criteria matching (comma OR, :not, :missing),
parameterized variable substitution, write constraint evaluation, wildcard
policy exclusions, hidden/readonly field reporting, unknown user denial,
and cryptographic audit integrity.
"""


import hashlib
import hmac as hmac_module
import json
import os
import subprocess
import pytest


EXPECTED_RESULTS = {
    "s01": {"decision": "allow"},
    "s02": {"decision": "deny"},
    "s03": {"decision": "allow"},
    "s04": {"decision": "deny"},
    "s05": {"decision": "allow"},
    "s06": {"decision": "deny"},
    "s07": {"decision": "allow"},
    "s08": {"decision": "deny"},
    "s09": {"decision": "allow"},
    "s10": {"decision": "allow"},
    "s11": {"decision": "deny"},
    "s12": {"decision": "deny"},
    "s13": {"decision": "allow", "hidden_fields": ["meta"]},
    "s14": {"decision": "deny"},
    "s15": {"decision": "allow"},
    "s16": {"decision": "allow"},
    "s17": {"decision": "allow"},
    "s18": {"decision": "allow"},
    "s19": {"decision": "allow"},
    "s20": {"decision": "deny"},
    "s21": {"decision": "allow"},
    "s22": {"decision": "deny"},
    "s23": {"decision": "allow"},
    "s24": {"decision": "deny"},
    "s25": {"decision": "allow"},
    "s26": {"decision": "allow"},
    "s27": {"decision": "deny"},
    "s28": {"decision": "allow"},
    "s29": {"decision": "deny"},
    "s30": {"decision": "allow", "readonly_fields": ["birthDate", "name"]},
    "s31": {"decision": "allow"},
    "s32": {"decision": "deny"},
    "s33": {"decision": "allow"},
    "s34": {"decision": "deny"},
    "s35": {"decision": "deny"},
}

AUDIT_KEY_PATH = "/app/data/audit_key.hex"


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the pipeline script before all tests."""
    assert os.path.exists("/app/run_pipeline.sh"), \
        "/app/run_pipeline.sh does not exist - the pipeline entry point must be created"
    result = subprocess.run(
        ["bash", "/app/run_pipeline.sh"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"run_pipeline.sh failed with exit code {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists("/app/results.json"), \
        "/app/results.json was not created by the pipeline"
    assert os.path.exists("/app/audit.json"), \
        "/app/audit.json was not created by the pipeline"


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def load_audit():
    with open("/app/audit.json") as f:
        return json.load(f)


def load_audit_key():
    with open(AUDIT_KEY_PATH) as f:
        return f.read().strip()


def compute_hmac(key_hex, message):
    key = bytes.fromhex(key_hex)
    return hmac_module.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


class TestAccessDecisions:
    """Verify that each scenario produces the correct allow/deny decision."""

    @pytest.mark.parametrize("scenario_id", sorted(EXPECTED_RESULTS.keys()))
    def test_decision(self, scenario_id):
        results = load_results()
        assert scenario_id in results, f"Scenario {scenario_id} missing from results.json"
        actual = results[scenario_id]
        expected = EXPECTED_RESULTS[scenario_id]
        assert actual["decision"] == expected["decision"], (
            f"Scenario {scenario_id}: "
            f"expected decision='{expected['decision']}', "
            f"got decision='{actual['decision']}'"
        )


class TestHiddenFields:
    """Verify hidden field reporting for read-allow scenarios."""

    @pytest.mark.parametrize(
        "scenario_id",
        [sid for sid, exp in EXPECTED_RESULTS.items() if "hidden_fields" in exp],
    )
    def test_hidden_fields_present(self, scenario_id):
        results = load_results()
        actual = results[scenario_id]
        expected = EXPECTED_RESULTS[scenario_id]
        actual_hidden = sorted(actual.get("hidden_fields", []))
        expected_hidden = sorted(expected["hidden_fields"])
        assert actual_hidden == expected_hidden, (
            f"Scenario {scenario_id}: "
            f"expected hidden_fields={expected_hidden}, "
            f"got hidden_fields={actual_hidden}"
        )

    @pytest.mark.parametrize(
        "scenario_id",
        [
            sid
            for sid, exp in EXPECTED_RESULTS.items()
            if "hidden_fields" not in exp and exp["decision"] == "allow"
        ],
    )
    def test_no_spurious_hidden_fields(self, scenario_id):
        results = load_results()
        actual = results[scenario_id]
        hidden = actual.get("hidden_fields", [])
        assert len(hidden) == 0, (
            f"Scenario {scenario_id}: "
            f"expected no hidden_fields but got {hidden}"
        )


class TestReadonlyFields:
    """Verify readonly field reporting for update-allow scenarios."""

    @pytest.mark.parametrize(
        "scenario_id",
        [sid for sid, exp in EXPECTED_RESULTS.items() if "readonly_fields" in exp],
    )
    def test_readonly_fields_present(self, scenario_id):
        results = load_results()
        actual = results[scenario_id]
        expected = EXPECTED_RESULTS[scenario_id]
        actual_readonly = sorted(actual.get("readonly_fields", []))
        expected_readonly = sorted(expected["readonly_fields"])
        assert actual_readonly == expected_readonly, (
            f"Scenario {scenario_id}: "
            f"expected readonly_fields={expected_readonly}, "
            f"got readonly_fields={actual_readonly}"
        )


class TestAuditIntegrity:
    """Verify HMAC-SHA256 audit log integrity."""

    def test_audit_is_dict(self):
        audit = load_audit()
        assert isinstance(audit, dict), "audit.json must contain a JSON object"

    def test_audit_completeness(self):
        audit = load_audit()
        missing = set(EXPECTED_RESULTS.keys()) - set(audit.keys())
        assert len(missing) == 0, f"Missing audit entries: {sorted(missing)}"

    @pytest.mark.parametrize("scenario_id", sorted(EXPECTED_RESULTS.keys()))
    def test_hmac_signature(self, scenario_id):
        audit = load_audit()
        key_hex = load_audit_key()
        expected_decision = EXPECTED_RESULTS[scenario_id]["decision"]
        canonical = f"{scenario_id}:{expected_decision}"
        expected_hmac = compute_hmac(key_hex, canonical)
        assert scenario_id in audit, f"Missing audit entry for {scenario_id}"
        assert audit[scenario_id] == expected_hmac, (
            f"Scenario {scenario_id}: HMAC mismatch. "
            f"Expected HMAC of '{canonical}' = {expected_hmac}, "
            f"got {audit[scenario_id]}"
        )


class TestResultsCompleteness:
    """Verify that results.json contains all expected scenarios."""

    def test_all_scenarios_present(self):
        results = load_results()
        missing = set(EXPECTED_RESULTS.keys()) - set(results.keys())
        assert len(missing) == 0, f"Missing scenarios in results: {sorted(missing)}"

    def test_results_is_dict(self):
        results = load_results()
        assert isinstance(results, dict), "results.json must contain a JSON object"
