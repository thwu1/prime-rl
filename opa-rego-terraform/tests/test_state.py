
import subprocess
import json
import os
import pytest


MANIFEST_PATH = "/app/manifest.json"


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def opa_eval(plan_path, policy_path, query):
    """Run OPA eval and return the boolean result value."""
    try:
        result = subprocess.run(
            [
                "opa", "eval",
                "-i", plan_path,
                "-d", policy_path,
                query,
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    try:
        output = json.loads(result.stdout)
        return output["result"][0]["expressions"][0]["value"]
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


manifest = load_manifest()


class TestPolicyStructure:
    """Verify policy files exist, are syntactically valid, and inspect plan data."""

    @pytest.mark.parametrize("policy_name", list(manifest["policies"].keys()))
    def test_policy_file_exists(self, policy_name):
        path = manifest["policies"][policy_name]["file"]
        assert os.path.exists(path), (
            f"Policy file for '{policy_name}' not found at {path}"
        )

    @pytest.mark.parametrize("policy_name", list(manifest["policies"].keys()))
    def test_policy_valid_rego_syntax(self, policy_name):
        path = manifest["policies"][policy_name]["file"]
        if not os.path.exists(path):
            pytest.skip(f"Policy file {path} does not exist")
        result = subprocess.run(
            ["opa", "check", path],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Policy '{policy_name}' has Rego syntax errors: {result.stderr}"
        )

    @pytest.mark.parametrize("policy_name", list(manifest["policies"].keys()))
    def test_policy_inspects_plan_data(self, policy_name):
        """Policies must reference input data, not return hardcoded results."""
        path = manifest["policies"][policy_name]["file"]
        if not os.path.exists(path):
            pytest.skip(f"Policy file {path} does not exist")
        with open(path) as f:
            content = f.read()
        assert "input." in content, (
            f"Policy '{policy_name}' does not reference input data — "
            f"policies must inspect Terraform plan content."
        )


# Build parametrized test cases from manifest
_test_cases = []
for policy_name, expected_map in manifest["expected_results"].items():
    policy_info = manifest["policies"][policy_name]
    for plan_name, expected_result in expected_map.items():
        plan_path = manifest["plans"][plan_name]
        _test_cases.append(
            pytest.param(
                policy_name,
                plan_name,
                policy_info["file"],
                plan_path,
                policy_info["query"],
                expected_result,
                id=f"{policy_name}--{plan_name}",
            )
        )


class TestPolicyEvaluation:
    """Verify each OPA policy produces the expected result against each Terraform plan."""

    @pytest.mark.parametrize(
        "policy_name,plan_name,policy_file,plan_file,query,expected",
        _test_cases,
    )
    def test_policy_evaluation(self, policy_name, plan_name, policy_file, plan_file, query, expected):
        assert os.path.exists(policy_file), (
            f"Policy file {policy_file} does not exist."
        )
        assert os.path.exists(plan_file), (
            f"Plan file {plan_file} does not exist."
        )

        result = opa_eval(plan_file, policy_file, query)
        assert result is not None, (
            f"OPA eval returned no result for policy '{policy_name}' against plan '{plan_name}'. "
            f"Check for syntax errors, undefined references, or query-package mismatches."
        )
        assert result == expected, (
            f"Policy '{policy_name}' against plan '{plan_name}': "
            f"expected {expected}, got {result}."
        )
