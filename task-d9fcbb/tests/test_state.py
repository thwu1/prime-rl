
import subprocess
import os
import re
import json
import pytest


@pytest.fixture(scope="session", autouse=True)
def init_terraform():
    """Run terraform init once before all tests."""
    result = subprocess.run(
        ["terraform", "init", "-no-color", "-input=false"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result


# ============================================================
# Evaluation tests — verify the solver judged proposals correctly
# ============================================================

class TestEvaluation:
    """Verify the solver produced a correct architectural evaluation."""

    def test_evaluation_file_exists(self):
        assert os.path.isfile("/app/evaluation.json"), \
            "evaluation.json not found at /app/evaluation.json"

    def test_evaluation_valid_json_with_required_keys(self):
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "evaluation.json must be a JSON object"
        required = [
            "proposal_a_assessment",
            "proposal_b_assessment",
            "selected_base",
            "selection_rationale",
        ]
        for key in required:
            assert key in data, f"evaluation.json missing required key: {key}"

    def test_proposal_a_domain_cohesion_violation_identified(self):
        """Proposal A groups by resource type — this violates domain cohesion."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        a_assessment = data.get("proposal_a_assessment", {})
        violations = a_assessment.get("violations", [])
        assert len(violations) > 0, \
            "Proposal A has architectural violations that must be identified"
        all_text = json.dumps(violations).lower()
        assert any(
            term in all_text
            for term in ["domain", "cohesion", "type", "group", "mix"]
        ), f"Proposal A violations should identify domain cohesion issue: {violations}"

    def test_proposal_b_bugs_identified(self):
        """Proposal B has correct architecture but implementation bugs."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        b_assessment = data.get("proposal_b_assessment", {})
        violations = b_assessment.get("violations", [])
        assert len(violations) > 0, \
            "Proposal B has implementation bugs that must be identified"

    def test_selected_base_is_proposal_b(self):
        """Domain-based Proposal B should be selected as the architectural base."""
        with open("/app/evaluation.json") as f:
            data = json.load(f)
        selected = str(data.get("selected_base", "")).lower()
        assert any(
            term in selected for term in ["b", "domain", "by_domain"]
        ), f"Should select Proposal B (by-domain) as base, got: {selected}"


# ============================================================
# Terraform validity tests
# ============================================================

class TestTerraformValidity:
    """Verify the implementation is syntactically valid and state-consistent."""

    def test_terraform_validate(self):
        result = subprocess.run(
            ["terraform", "validate", "-no-color"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, \
            f"terraform validate failed:\n{result.stdout}\n{result.stderr}"

    def test_terraform_plan_zero_changes(self):
        result = subprocess.run(
            ["terraform", "plan", "-no-color", "-input=false"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + "\n" + result.stderr
        assert result.returncode in (0, 2), \
            f"terraform plan errored (exit {result.returncode}):\n{output}"

        if "No changes" in output:
            return

        add_match = re.search(r"(\d+) to add", output)
        destroy_match = re.search(r"(\d+) to destroy", output)

        if add_match:
            assert int(add_match.group(1)) == 0, \
                f"Plan adds resources:\n{output}"
        if destroy_match:
            assert int(destroy_match.group(1)) == 0, \
                f"Plan destroys resources:\n{output}"

        assert "must be replaced" not in output, \
            f"Forced replacements detected:\n{output}"
        assert "forces replacement" not in output, \
            f"Forced replacements detected:\n{output}"


# ============================================================
# Module architecture tests
# ============================================================

class TestModuleArchitecture:
    """Verify the implementation uses domain-based module structure."""

    def test_domain_modules_exist(self):
        for module_name in ["network", "application", "monitoring"]:
            module_dir = f"/app/modules/{module_name}"
            assert os.path.isdir(module_dir), \
                f"Module directory {module_dir} missing"
            tf_files = [f for f in os.listdir(module_dir) if f.endswith(".tf")]
            assert len(tf_files) > 0, \
                f"No .tf files in modules/{module_name}/"

    def test_no_type_based_modules(self):
        """Must not use Proposal A's by-type grouping."""
        assert not os.path.isdir("/app/modules/files"), \
            "modules/files/ is by-type grouping — violates domain cohesion"
        assert not os.path.isdir("/app/modules/runtime"), \
            "modules/runtime/ is by-type grouping — violates domain cohesion"
        assert not os.path.isdir("/app/modules/triggers"), \
            "modules/triggers/ is by-type grouping — violates domain cohesion"

    def test_root_references_all_domain_modules(self):
        root_tf = ""
        for f in os.listdir("/app"):
            if f.endswith(".tf"):
                with open(f"/app/{f}") as fh:
                    root_tf += fh.read() + "\n"

        for mod in ["network", "application", "monitoring"]:
            assert re.search(rf'module\s+"{mod}"', root_tf), \
                f'Root config must reference module "{mod}"'

    def test_network_resources_not_in_root(self):
        root_tf = ""
        for f in os.listdir("/app"):
            if f.endswith(".tf"):
                with open(f"/app/{f}") as fh:
                    root_tf += fh.read() + "\n"
        assert not re.search(
            r'resource\s+"local_file"\s+"network_config"', root_tf
        ), "network_config should be in network module, not root"
        assert not re.search(
            r'resource\s+"local_file"\s+"subnet_configs"', root_tf
        ), "subnet_configs should be in network module, not root"

    def test_app_resources_not_in_root(self):
        root_tf = ""
        for f in os.listdir("/app"):
            if f.endswith(".tf"):
                with open(f"/app/{f}") as fh:
                    root_tf += fh.read() + "\n"
        assert not re.search(
            r'resource\s+"local_file"\s+"app_configs"', root_tf
        ), "app_configs should be in application module, not root"
        assert not re.search(
            r'resource\s+"null_resource"\s+"health_check"', root_tf
        ), "health_check should be in application module, not root"

    def test_monitoring_resources_not_in_root(self):
        root_tf = ""
        for f in os.listdir("/app"):
            if f.endswith(".tf"):
                with open(f"/app/{f}") as fh:
                    root_tf += fh.read() + "\n"
        assert not re.search(
            r'resource\s+"local_file"\s+"alert_rules"', root_tf
        ), "alert_rules should be in monitoring module, not root"
        assert not re.search(
            r'resource\s+"null_resource"\s+"alert_notifier"', root_tf
        ), "alert_notifier should be in monitoring module, not root"

    def test_modules_have_validation_blocks(self):
        """Each module must have at least one validation block per ARCHITECTURE.md."""
        for module_name in ["network", "application", "monitoring"]:
            module_dir = f"/app/modules/{module_name}"
            module_tf = ""
            for f in os.listdir(module_dir):
                if f.endswith(".tf"):
                    with open(os.path.join(module_dir, f)) as fh:
                        module_tf += fh.read() + "\n"
            assert "validation" in module_tf, \
                f"Module {module_name} must have at least one validation block"


# ============================================================
# State migration tests
# ============================================================

class TestStateMigration:
    """Verify state migration uses moved blocks."""

    def test_moved_blocks_exist(self):
        moved_found = False
        for root, dirs, files in os.walk("/app"):
            dirs[:] = [d for d in dirs if d not in (".terraform", "proposals")]
            for f in files:
                if f.endswith(".tf"):
                    with open(os.path.join(root, f)) as fh:
                        if re.search(r"\bmoved\s*\{", fh.read()):
                            moved_found = True
                            break
            if moved_found:
                break
        assert moved_found, "No moved blocks found for state migration"

    def test_sufficient_moved_blocks(self):
        """Must have moved blocks for all 8 resource types being migrated."""
        moved_count = 0
        for root, dirs, files in os.walk("/app"):
            dirs[:] = [d for d in dirs if d not in (".terraform", "proposals")]
            for f in files:
                if f.endswith(".tf"):
                    with open(os.path.join(root, f)) as fh:
                        content = fh.read()
                        moved_count += len(re.findall(r"\bmoved\s*\{", content))
        assert moved_count >= 8, \
            f"Found {moved_count} moved blocks; need at least 8 for all resource migrations"


# ============================================================
# Variable validation tests
# ============================================================

class TestVariableValidation:
    """Verify domain-appropriate variable validation exists and works."""

    def test_environment_validation_rejects_invalid(self):
        result = subprocess.run(
            [
                "terraform", "plan",
                "-var", "environment=invalid-env",
                "-no-color", "-input=false",
            ],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode != 0, \
            "Should reject invalid environment value"

    def test_environment_validation_accepts_valid(self):
        for env in ["production", "staging", "development"]:
            result = subprocess.run(
                [
                    "terraform", "plan",
                    "-var", f"environment={env}",
                    "-no-color", "-input=false",
                ],
                cwd="/app",
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode in (0, 2), \
                f"Should accept environment={env}:\n{result.stdout}\n{result.stderr}"

    def test_port_validation_rejects_privileged(self):
        """Port validation must reject ports below 1024."""
        tfvars = "/tmp/test_bad_port.tfvars"
        with open(tfvars, "w") as f:
            f.write(
                'app_config = {\n'
                '  bad_svc = {\n'
                '    port     = 80\n'
                '    replicas = 1\n'
                '    enabled  = true\n'
                '  }\n'
                '}\n'
            )
        try:
            result = subprocess.run(
                [
                    "terraform", "plan",
                    "-var-file", tfvars,
                    "-no-color", "-input=false",
                ],
                cwd="/app",
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode != 0, \
                "Should reject port 80 (below 1024)"
        finally:
            if os.path.exists(tfvars):
                os.remove(tfvars)

    def test_severity_validation_rejects_invalid(self):
        """Alert severity validation must reject invalid values."""
        tfvars = "/tmp/test_bad_severity.tfvars"
        with open(tfvars, "w") as f:
            f.write(
                'alert_endpoints = {\n'
                '  bad = {\n'
                '    url      = "https://example.com"\n'
                '    severity = "catastrophic"\n'
                '    active   = true\n'
                '  }\n'
                '}\n'
            )
        try:
            result = subprocess.run(
                [
                    "terraform", "plan",
                    "-var-file", tfvars,
                    "-no-color", "-input=false",
                ],
                cwd="/app",
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode != 0, \
                "Should reject severity 'catastrophic'"
        finally:
            if os.path.exists(tfvars):
                os.remove(tfvars)
