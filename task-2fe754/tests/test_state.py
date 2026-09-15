"""Verify workspace feature resolution audit: diagnostic report + architecture + builds.

"""

import subprocess
import tomllib


def _load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _cargo(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["cargo"] + args,
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Diagnostic report tests
# ---------------------------------------------------------------------------


class TestDiagnosticReport:
    def test_report_has_analysis_section(self):
        """migration_report.toml must exist with an [analysis] section."""
        data = _load_toml("/app/migration_report.toml")
        assert "analysis" in data, "Report must contain [analysis] section"

    def test_implicit_feature_count(self):
        """Must correctly count the distinct implicit feature dependencies."""
        data = _load_toml("/app/migration_report.toml")
        count = data["analysis"]["implicit_feature_count"]
        assert count == 2, f"Expected 2 implicit feature deps, got {count}"

    def test_testfixture_misuse_crate(self):
        """Must identify signal-net as the crate misusing TestFixture outside cfg(test)."""
        data = _load_toml("/app/migration_report.toml")
        crate = data["analysis"]["testfixture_misuse_crate"]
        assert crate == "signal-net", f"Expected 'signal-net', got {crate!r}"

    def test_storage_missing_feature(self):
        """Must identify 'std' as the feature signal-storage implicitly depends on."""
        data = _load_toml("/app/migration_report.toml")
        feat = data["analysis"]["storage_missing_feature"]
        assert feat == "std", f"Expected 'std', got {feat!r}"

    def test_storage_uses_module(self):
        """Must identify 'io' as the signal-core module requiring the undeclared feature."""
        data = _load_toml("/app/migration_report.toml")
        mod_name = data["analysis"]["storage_uses_module"]
        assert mod_name == "io", f"Expected 'io', got {mod_name!r}"

    def test_net_leak_section(self):
        """Must identify 'dev-dependencies' as the section leaking test-utils."""
        data = _load_toml("/app/migration_report.toml")
        section = data["analysis"]["net_leak_section"]
        assert section == "dev-dependencies", (
            f"Expected 'dev-dependencies', got {section!r}"
        )


# ---------------------------------------------------------------------------
# Workspace architecture tests
# ---------------------------------------------------------------------------


class TestWorkspaceArchitecture:
    def test_resolver_version(self):
        """Workspace root must use resolver = "2"."""
        root = _load_toml("/app/Cargo.toml")
        resolver = root.get("workspace", {}).get("resolver")
        assert resolver == "2", f"Expected resolver='2', got {resolver!r}"

    def test_workspace_deps_serde(self):
        """serde must be declared in [workspace.dependencies]."""
        root = _load_toml("/app/Cargo.toml")
        ws_deps = root.get("workspace", {}).get("dependencies", {})
        assert "serde" in ws_deps, "serde not in workspace.dependencies"

    def test_workspace_deps_serde_json(self):
        """serde_json must be declared in [workspace.dependencies]."""
        root = _load_toml("/app/Cargo.toml")
        ws_deps = root.get("workspace", {}).get("dependencies", {})
        assert "serde_json" in ws_deps, "serde_json not in workspace.dependencies"

    def test_workspace_deps_signal_core(self):
        """signal-core must be declared in [workspace.dependencies]."""
        root = _load_toml("/app/Cargo.toml")
        ws_deps = root.get("workspace", {}).get("dependencies", {})
        assert "signal-core" in ws_deps, "signal-core not in workspace.dependencies"


class TestMemberArchitecture:
    def test_storage_explicit_std(self):
        """signal-storage must explicitly enable 'std' on signal-core."""
        manifest = _load_toml("/app/signal-storage/Cargo.toml")
        core_dep = manifest.get("dependencies", {}).get("signal-core", {})
        assert isinstance(core_dep, dict), "signal-core dep should be a table"
        features = core_dep.get("features", [])
        assert "std" in features, (
            f"signal-storage must enable 'std' on signal-core, got features={features}"
        )

    def test_net_workspace_serde(self):
        """signal-net must reference serde via workspace inheritance."""
        manifest = _load_toml("/app/signal-net/Cargo.toml")
        serde_dep = manifest.get("dependencies", {}).get("serde", {})
        assert isinstance(serde_dep, dict), "serde dep should be a table"
        assert serde_dep.get("workspace") is True, (
            "signal-net should inherit serde from workspace"
        )

    def test_storage_workspace_serde(self):
        """signal-storage must reference serde via workspace inheritance."""
        manifest = _load_toml("/app/signal-storage/Cargo.toml")
        serde_dep = manifest.get("dependencies", {}).get("serde", {})
        assert isinstance(serde_dep, dict), "serde dep should be a table"
        assert serde_dep.get("workspace") is True, (
            "signal-storage should inherit serde from workspace"
        )


# ---------------------------------------------------------------------------
# Compilation tests
# ---------------------------------------------------------------------------


class TestCompilation:
    def test_cargo_check_workspace(self):
        """cargo check --workspace must succeed."""
        result = _cargo(["check", "--workspace"])
        assert result.returncode == 0, (
            f"cargo check --workspace failed:\n{result.stderr[:3000]}"
        )

    def test_cargo_check_storage_standalone(self):
        """cargo check -p signal-storage must succeed in isolation."""
        result = _cargo(["check", "-p", "signal-storage"])
        assert result.returncode == 0, (
            f"cargo check -p signal-storage failed:\n{result.stderr[:3000]}"
        )

    def test_cargo_check_net_standalone(self):
        """cargo check -p signal-net must succeed in isolation."""
        result = _cargo(["check", "-p", "signal-net"])
        assert result.returncode == 0, (
            f"cargo check -p signal-net failed:\n{result.stderr[:3000]}"
        )

    def test_cargo_test_net(self):
        """cargo test -p signal-net must pass."""
        result = _cargo(["test", "-p", "signal-net"], timeout=300)
        assert result.returncode == 0, (
            f"cargo test -p signal-net failed:\n{result.stderr[:3000]}"
        )
