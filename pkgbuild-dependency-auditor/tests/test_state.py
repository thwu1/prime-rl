
import json
import os
import re
import sqlite3

import pytest

REPORT_PATH = "/app/report.json"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), "report.json not found at /app/report.json"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Package parsing tests
# ---------------------------------------------------------------------------

class TestPackageParsing:
    def test_report_structure(self, report):
        assert isinstance(report, dict)
        assert "packages" in report
        assert "issues" in report
        assert "build_order" in report

    def test_package_count(self, report):
        """13 individual packages from 8 pkgbases."""
        pkgs = report["packages"]
        assert len(pkgs) == 13, (
            f"Expected 13 packages, got {len(pkgs)}: {sorted(pkgs.keys())}"
        )

    def test_all_package_names(self, report):
        expected = {
            "syslibs", "syslibs-dev", "syslibs-tools",
            "webstack",
            "appserver", "appserver-modules",
            "dbengine", "dbengine-client", "dbengine-libs",
            "monitor", "frontend", "analytics", "dashboard",
        }
        actual = set(report["packages"].keys())
        assert actual == expected, (
            f"Missing: {expected - actual}, Extra: {actual - expected}"
        )

    def test_epoch_version_syslibs(self, report):
        v = report["packages"]["syslibs"]["version"]
        assert v == "1:3.2.1-2", f"Expected 1:3.2.1-2, got {v}"

    def test_epoch_propagates_to_split_packages(self, report):
        for name in ("syslibs-dev", "syslibs-tools"):
            v = report["packages"][name]["version"]
            assert v == "1:3.2.1-2", (
                f"{name} version should be 1:3.2.1-2, got {v}"
            )

    def test_no_epoch_version(self, report):
        v = report["packages"]["webstack"]["version"]
        assert v == "2.4.6-1", f"Expected 2.4.6-1, got {v}"

    def test_variable_substitution_makedepends(self, report):
        """appserver makedepends should resolve ${_runtime} to nodejs."""
        makedeps = report["packages"]["appserver"]["makedepends"]
        assert "nodejs" in makedeps, f"'nodejs' not in makedepends: {makedeps}"

    def test_variable_substitution_depends(self, report):
        """appserver depends should resolve ${_runtime} to nodejs."""
        deps = report["packages"]["appserver"]["depends"]
        assert "nodejs" in deps, f"'nodejs' not in depends: {deps}"

    def test_variable_concat_substitution(self, report):
        """frontend depends should resolve electron${_electronVersion} to electron28."""
        deps = report["packages"]["frontend"]["depends"]
        assert "electron28" in deps, f"'electron28' not in depends: {deps}"

    def test_split_package_syslibs_deps(self, report):
        assert set(report["packages"]["syslibs"]["depends"]) == {"glibc", "zlib"}

    def test_split_package_syslibs_dev_deps(self, report):
        assert set(report["packages"]["syslibs-dev"]["depends"]) == {"syslibs"}

    def test_split_package_syslibs_tools_deps(self, report):
        assert set(report["packages"]["syslibs-tools"]["depends"]) == {
            "syslibs", "openssl",
        }

    def test_provides_syslibs(self, report):
        provs = report["packages"]["syslibs"].get("provides", [])
        assert "libcompat=3.2.1" in provs, f"Expected libcompat=3.2.1: {provs}"

    def test_provides_webstack(self, report):
        provs = report["packages"]["webstack"].get("provides", [])
        assert "http-server=2.4.6" in provs, f"Expected http-server=2.4.6: {provs}"

    def test_provides_dbengine_libs(self, report):
        provs = report["packages"]["dbengine-libs"].get("provides", [])
        assert "libcompat=9.2.0" in provs, f"Expected libcompat=9.2.0: {provs}"

    def test_conflicts_appserver(self, report):
        confs = report["packages"]["appserver"].get("conflicts", [])
        assert "legacy-appserver" in confs, f"Expected legacy-appserver: {confs}"

    def test_pkgbase_split(self, report):
        assert report["packages"]["syslibs"]["pkgbase"] == "syslibs"
        assert report["packages"]["syslibs-dev"]["pkgbase"] == "syslibs"
        assert report["packages"]["syslibs-tools"]["pkgbase"] == "syslibs"

    def test_pkgbase_dbengine(self, report):
        for name in ("dbengine", "dbengine-client", "dbengine-libs"):
            assert report["packages"][name]["pkgbase"] == "dbengine"

    def test_pkgbase_single(self, report):
        assert report["packages"]["webstack"]["pkgbase"] == "webstack"
        assert report["packages"]["monitor"]["pkgbase"] == "monitor"

    def test_dbengine_internal_deps(self, report):
        """dbengine -> dbengine-client -> dbengine-libs dependency chain."""
        assert "dbengine-client" in report["packages"]["dbengine"]["depends"]
        assert "dbengine-libs" in report["packages"]["dbengine-client"]["depends"]

    def test_webstack_versioned_dep_preserved(self, report):
        """webstack depends must preserve the version constraint on openssl."""
        deps = report["packages"]["webstack"]["depends"]
        assert any("openssl" in d and ">=" in d for d in deps), (
            f"Expected versioned openssl dep (openssl>=...) in webstack depends: {deps}"
        )


# ---------------------------------------------------------------------------
# Issue detection tests
# ---------------------------------------------------------------------------

class TestIssueDetection:
    def _of_type(self, report, t):
        return [i for i in report["issues"] if i["type"] == t]

    def test_missing_dep_plugin_framework(self, report):
        missing = self._of_type(report, "missing_dependency")
        hits = [
            i for i in missing
            if i.get("missing") == "plugin-framework"
            and i.get("package") == "appserver-modules"
        ]
        assert len(hits) >= 1, (
            "Expected missing_dependency for appserver-modules -> plugin-framework"
        )

    def test_missing_dep_electron28(self, report):
        missing = self._of_type(report, "missing_dependency")
        hits = [
            i for i in missing
            if i.get("missing") == "electron28"
            and i.get("package") == "frontend"
        ]
        assert len(hits) >= 1, (
            "Expected missing_dependency for frontend -> electron28"
        )

    def test_conflicting_provides_libcompat(self, report):
        conflicts = self._of_type(report, "conflicting_provides")
        hits = [i for i in conflicts if i.get("provides") == "libcompat"]
        assert len(hits) >= 1, "Expected conflicting_provides for libcompat"
        providers = set(hits[0].get("packages", []))
        assert "syslibs" in providers, f"syslibs missing from providers: {providers}"
        assert "dbengine-libs" in providers, (
            f"dbengine-libs missing from providers: {providers}"
        )

    def test_version_constraint_violation_internal(self, report):
        """Detects version violation for internal package: monitor -> webstack>=3.0.0."""
        violations = self._of_type(report, "version_constraint_violation")
        hits = [
            i for i in violations
            if i.get("package") == "monitor"
            and "webstack" in i.get("dependency", "")
        ]
        assert len(hits) >= 1, (
            "Expected version_constraint_violation for monitor -> webstack>=3.0.0"
        )

    def test_version_constraint_violation_external(self, report):
        """Detects version violation against external registry package: webstack -> openssl>=3.3.0."""
        violations = self._of_type(report, "version_constraint_violation")
        hits = [
            i for i in violations
            if i.get("package") == "webstack"
            and "openssl" in i.get("dependency", "")
        ]
        assert len(hits) >= 1, (
            "Expected version_constraint_violation for webstack -> openssl>=3.3.0 "
            "(registry has openssl 3.2.1-1)"
        )

    def test_circular_dependency(self, report):
        cycles = self._of_type(report, "circular_dependency")
        assert len(cycles) >= 1, "Expected at least one circular_dependency"
        found = False
        for c in cycles:
            members = set(c.get("cycle", []))
            if "analytics" in members and "dashboard" in members:
                found = True
                break
        assert found, (
            f"Expected cycle containing analytics and dashboard, got {cycles}"
        )

    def test_all_issue_types_present(self, report):
        types_found = {i["type"] for i in report["issues"]}
        expected = {
            "missing_dependency",
            "conflicting_provides",
            "version_constraint_violation",
            "circular_dependency",
        }
        assert expected.issubset(types_found), (
            f"Missing issue types: {expected - types_found}"
        )

    def test_issue_count_lower_bound(self, report):
        """At least 6 issues: 2 missing, 1 conflict, 2 version violations, 1 cycle."""
        assert len(report["issues"]) >= 6, (
            f"Expected >= 6 issues, got {len(report['issues'])}"
        )


# ---------------------------------------------------------------------------
# Build order tests
# ---------------------------------------------------------------------------

class TestBuildOrder:
    def test_build_order_is_list(self, report):
        assert isinstance(report["build_order"], list)

    def test_excludes_circular_analytics(self, report):
        assert "analytics" not in report["build_order"]

    def test_excludes_circular_dashboard(self, report):
        assert "dashboard" not in report["build_order"]

    def test_includes_syslibs(self, report):
        assert "syslibs" in report["build_order"]

    def test_includes_webstack(self, report):
        assert "webstack" in report["build_order"]

    def test_includes_dbengine(self, report):
        assert "dbengine" in report["build_order"]

    def test_includes_appserver(self, report):
        assert "appserver" in report["build_order"]

    def test_syslibs_before_webstack(self, report):
        order = report["build_order"]
        assert order.index("syslibs") < order.index("webstack")

    def test_syslibs_before_dbengine(self, report):
        order = report["build_order"]
        assert order.index("syslibs") < order.index("dbengine")

    def test_syslibs_before_appserver(self, report):
        order = report["build_order"]
        assert order.index("syslibs") < order.index("appserver")

    def test_webstack_before_appserver(self, report):
        order = report["build_order"]
        assert order.index("webstack") < order.index("appserver")

    def test_topological_validity(self, report):
        """Every pkgbase dependency that is also in the order must appear earlier."""
        order = report["build_order"]
        packages = report["packages"]
        position = {b: i for i, b in enumerate(order)}

        # Map: package-name -> pkgbase
        pkg_to_base = {}
        base_to_pkgs = {}
        for name, meta in packages.items():
            b = meta["pkgbase"]
            pkg_to_base[name] = b
            base_to_pkgs.setdefault(b, []).append(name)

        # Map: provided-name -> pkgbase
        prov_to_base = {}
        for name, meta in packages.items():
            prov_to_base[name] = meta["pkgbase"]
            for p in meta.get("provides", []):
                prov_name = re.split(r"[><=]", p)[0]
                prov_to_base[prov_name] = meta["pkgbase"]

        available = set()
        db_path = "/app/registry.db"
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            available = set(
                row[0] for row in conn.execute("SELECT name FROM packages")
            )
            conn.close()

        for base in order:
            for pkg_name in base_to_pkgs.get(base, []):
                meta = packages[pkg_name]
                all_deps = meta.get("depends", []) + meta.get("makedepends", [])
                for dep in all_deps:
                    dep_name = re.split(r"[><=]", dep)[0]
                    if dep_name in available:
                        continue
                    if dep_name in prov_to_base:
                        dep_base = prov_to_base[dep_name]
                        if dep_base == base:
                            continue
                        if dep_base in position:
                            assert position[dep_base] < position[base], (
                                f"Topological violation: {base} needs {dep_base} "
                                f"(via {dep_name}) but it comes later"
                            )
