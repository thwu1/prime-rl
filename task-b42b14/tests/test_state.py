
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest


def fnv1a_64(data: bytes) -> int:
    """Independent FNV-1a 64-bit hash for verification."""
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def cargo(args, timeout=600):
    """Run a cargo command in the workspace."""
    return subprocess.run(
        ["cargo"] + args,
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# 1. Migration report structure and content
# ---------------------------------------------------------------------------

class TestMigrationReportExists:
    def test_report_file_exists(self):
        assert os.path.exists("/app/migration_report.json"), \
            "migration_report.json must exist at /app/"

    def test_report_valid_json(self):
        with open("/app/migration_report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Report root must be a JSON object"
        assert "issues" in data, "Report must have an 'issues' key"
        assert isinstance(data["issues"], list), "'issues' must be a list"


class TestMigrationReportContent:
    @pytest.fixture(scope="class")
    def report(self):
        with open("/app/migration_report.json") as f:
            return json.load(f)

    def test_issue_count(self, report):
        assert len(report["issues"]) == 7, \
            f"Expected 7 issues, got {len(report['issues'])}"

    def test_required_fields(self, report):
        required = {"crate_name", "file", "category", "dependency", "detail"}
        for i, issue in enumerate(report["issues"]):
            missing = required - set(issue.keys())
            assert not missing, f"Issue #{i} missing fields: {missing}"

    def test_all_categories_present(self, report):
        cats = {i["category"] for i in report["issues"]}
        expected = {
            "dep_not_optional", "dev_dep_leak", "host_dep_leak",
            "missing_feature", "workspace_feature_gap", "broken_propagation",
        }
        assert cats == expected, f"Expected categories {expected}, got {cats}"

    # -- dep_not_optional --
    def test_dep_not_optional_count(self, report):
        issues = [i for i in report["issues"] if i["category"] == "dep_not_optional"]
        assert len(issues) == 2

    def test_dep_not_optional_deps(self, report):
        issues = [i for i in report["issues"] if i["category"] == "dep_not_optional"]
        deps = {i["dependency"] for i in issues}
        assert deps == {"serde", "serde_json"}, f"Got deps: {deps}"

    def test_dep_not_optional_crate(self, report):
        issues = [i for i in report["issues"] if i["category"] == "dep_not_optional"]
        crates = {i["crate_name"] for i in issues}
        assert crates == {"foundation"}, f"Got crates: {crates}"

    # -- dev_dep_leak --
    def test_dev_dep_leak(self, report):
        issues = [i for i in report["issues"] if i["category"] == "dev_dep_leak"]
        assert len(issues) == 1
        assert issues[0]["crate_name"] == "codec"
        assert issues[0]["dependency"] == "foundation"

    # -- host_dep_leak --
    def test_host_dep_leak(self, report):
        issues = [i for i in report["issues"] if i["category"] == "host_dep_leak"]
        assert len(issues) == 1
        assert issues[0]["crate_name"] == "server"
        assert issues[0]["dependency"] == "foundation"

    # -- missing_feature --
    def test_missing_feature(self, report):
        issues = [i for i in report["issues"] if i["category"] == "missing_feature"]
        assert len(issues) == 1
        assert issues[0]["crate_name"] == "validator"
        assert issues[0]["dependency"] == "foundation"

    # -- workspace_feature_gap --
    def test_workspace_feature_gap(self, report):
        issues = [i for i in report["issues"] if i["category"] == "workspace_feature_gap"]
        assert len(issues) == 1
        assert issues[0]["dependency"] == "serde"

    # -- broken_propagation --
    def test_broken_propagation(self, report):
        issues = [i for i in report["issues"] if i["category"] == "broken_propagation"]
        assert len(issues) == 1
        assert issues[0]["crate_name"] == "server"
        assert issues[0]["dependency"] == "foundation"


# ---------------------------------------------------------------------------
# 2. Analyzer tool is dynamic (not hardcoded)
# ---------------------------------------------------------------------------

class TestAnalyzerDynamic:
    def test_tool_exists(self):
        assert os.path.exists("/app/migration_analyzer.py"), \
            "migration_analyzer.py must exist at /app/"

    def test_zero_issues_on_fixed_workspace(self):
        """Re-running the analyzer on the already-fixed workspace must find 0 issues."""
        result = subprocess.run(
            ["python3", "/app/migration_analyzer.py",
             "--output", "/tmp/recheck_report.json"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, \
            f"Analyzer failed on fixed workspace:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        with open("/tmp/recheck_report.json") as f:
            data = json.load(f)
        assert len(data["issues"]) == 0, (
            f"Expected 0 issues on fixed workspace, got {len(data['issues'])}:\n"
            + json.dumps(data["issues"], indent=2)
        )

    def test_detects_reintroduced_dep_not_optional(self):
        """Remove optional=true from a dep and verify the tool catches it."""
        tmpdir = tempfile.mkdtemp()
        try:
            ws_copy = os.path.join(tmpdir, "ws")
            shutil.copytree(
                "/app", ws_copy, symlinks=True,
                ignore=shutil.ignore_patterns("target", ".git"),
            )
            # Remove ', optional = true' from foundation's Cargo.toml
            toml_path = os.path.join(ws_copy, "crates/foundation/Cargo.toml")
            with open(toml_path) as f:
                content = f.read()
            content = content.replace(", optional = true", "")
            with open(toml_path, "w") as f:
                f.write(content)

            report_path = os.path.join(tmpdir, "report.json")
            result = subprocess.run(
                ["python3", "/app/migration_analyzer.py",
                 "--workspace", ws_copy,
                 "--output", report_path],
                capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, \
                f"Analyzer failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            with open(report_path) as f:
                data = json.load(f)
            dep_issues = [
                i for i in data["issues"]
                if i["category"] == "dep_not_optional"
            ]
            assert len(dep_issues) >= 1, (
                f"Tool should detect dep_not_optional after removing optional flag. "
                f"Got: {json.dumps(data['issues'], indent=2)}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. Workspace compiles and tests pass under resolver v2
# ---------------------------------------------------------------------------

class TestWorkspaceCompilation:
    def test_resolver_v2(self):
        import tomllib
        with open("/app/Cargo.toml", "rb") as f:
            data = tomllib.load(f)
        resolver = data.get("workspace", {}).get("resolver", "1")
        assert resolver == "2", f"Resolver must be '2', got '{resolver}'"

    def test_check_foundation(self):
        r = cargo(["check", "-p", "foundation"])
        assert r.returncode == 0, f"cargo check -p foundation failed:\n{r.stderr}"

    def test_check_codec(self):
        r = cargo(["check", "-p", "codec"])
        assert r.returncode == 0, f"cargo check -p codec failed:\n{r.stderr}"

    def test_check_buildutil(self):
        r = cargo(["check", "-p", "buildutil"])
        assert r.returncode == 0, f"cargo check -p buildutil failed:\n{r.stderr}"

    def test_check_validator(self):
        r = cargo(["check", "-p", "validator"])
        assert r.returncode == 0, f"cargo check -p validator failed:\n{r.stderr}"

    def test_check_transform(self):
        r = cargo(["check", "-p", "transform"])
        assert r.returncode == 0, f"cargo check -p transform failed:\n{r.stderr}"

    def test_check_server(self):
        r = cargo(["check", "-p", "server"])
        assert r.returncode == 0, f"cargo check -p server failed:\n{r.stderr}"

    def test_check_workspace(self):
        r = cargo(["check", "--workspace"])
        assert r.returncode == 0, f"cargo check --workspace failed:\n{r.stderr}"

    def test_test_workspace(self):
        r = cargo(["test", "--workspace"])
        assert r.returncode == 0, f"cargo test --workspace failed:\n{r.stderr}"


# ---------------------------------------------------------------------------
# 4. Server binary produces correct output
# ---------------------------------------------------------------------------

class TestServerBinary:
    @pytest.fixture(scope="class")
    def server_run(self):
        return cargo(["run", "-p", "server"], timeout=300)

    def test_server_runs(self, server_run):
        assert server_run.returncode == 0, (
            f"server exited non-zero:\nstdout:\n{server_run.stdout}\n"
            f"stderr:\n{server_run.stderr}"
        )

    def test_protocol_magic_value(self, server_run):
        assert server_run.returncode == 0, f"server failed:\n{server_run.stderr}"
        expected = fnv1a_64(b"server-protocol-v1")
        expected_str = f"Protocol magic: {expected:#018x}"
        assert expected_str in server_run.stdout, \
            f"Expected '{expected_str}' in:\n{server_run.stdout}"

    def test_envelope_ok(self, server_run):
        assert server_run.returncode == 0
        assert "Envelope OK" in server_run.stdout, \
            f"Missing 'Envelope OK' in:\n{server_run.stdout}"

    def test_packet_hash(self, server_run):
        assert server_run.returncode == 0
        found = False
        for line in server_run.stdout.splitlines():
            if line.startswith("Packet hash:"):
                val = int(line.split(":")[1].strip())
                assert val != 0, "packet hash is zero"
                found = True
                break
        assert found, f"Missing 'Packet hash:' in:\n{server_run.stdout}"

    def test_validation_strict(self, server_run):
        assert server_run.returncode == 0
        assert "Validation: strict" in server_run.stdout, \
            f"Missing 'Validation: strict' in:\n{server_run.stdout}"

    def test_all_checks_passed(self, server_run):
        assert server_run.returncode == 0
        assert "All checks passed" in server_run.stdout, \
            f"Missing 'All checks passed' in:\n{server_run.stdout}"
