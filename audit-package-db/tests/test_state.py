
import json
import os
import pytest


@pytest.fixture
def report():
    report_path = "/app/audit_report.json"
    assert os.path.exists(report_path), "audit_report.json not found at /app/"
    with open(report_path) as f:
        data = json.load(f)
    return data


class TestReportStructure:
    def test_has_all_keys(self, report):
        required = {
            "integrity_failures",
            "unsatisfied_dependencies",
            "dependency_cycles",
            "file_conflicts",
            "orphaned_packages",
        }
        assert required.issubset(set(report.keys())), (
            f"Missing keys: {required - set(report.keys())}"
        )

    def test_all_values_are_lists(self, report):
        for key in [
            "integrity_failures",
            "unsatisfied_dependencies",
            "dependency_cycles",
            "file_conflicts",
            "orphaned_packages",
        ]:
            assert isinstance(report[key], list), f"{key} should be a list"


class TestIntegrityFailures:
    def test_correct_packages_detected(self, report):
        failures = report["integrity_failures"]
        failed_pkgs = {f["package"] for f in failures}
        assert failed_pkgs == {"libcrypto", "renderer"}, (
            f"Expected integrity failures for libcrypto and renderer, got {failed_pkgs}"
        )

    def test_count(self, report):
        assert len(report["integrity_failures"]) == 2

    def test_hashes_differ(self, report):
        for f in report["integrity_failures"]:
            assert "expected_sha256" in f, "Missing expected_sha256 field"
            assert "actual_sha256" in f, "Missing actual_sha256 field"
            assert f["expected_sha256"] != f["actual_sha256"], (
                f"Hashes should differ for {f['package']}"
            )

    def test_no_false_positives(self, report):
        failed_pkgs = {f["package"] for f in report["integrity_failures"]}
        known_good = {"libcore", "libnet", "libui", "httpd", "dbengine",
                      "cli-tools", "backup", "webapp"}
        assert failed_pkgs & known_good == set(), (
            f"False positives: {failed_pkgs & known_good}"
        )


class TestUnsatisfiedDependencies:
    def test_count(self, report):
        unsatisfied = report["unsatisfied_dependencies"]
        assert len(unsatisfied) == 5, (
            f"Expected 5 unsatisfied deps, got {len(unsatisfied)}: "
            f"{[(u['package'], u.get('dependency','?')) for u in unsatisfied]}"
        )

    def test_httpd_libnet(self, report):
        httpd_viols = [
            u for u in report["unsatisfied_dependencies"]
            if u["package"] == "httpd"
        ]
        assert len(httpd_viols) == 1, "httpd should have exactly 1 violation"
        v = httpd_viols[0]
        assert "libnet" in v["dependency"]
        assert v["installed_version"] == "2.9.0"

    def test_sshd_libnet(self, report):
        sshd_viols = [
            u for u in report["unsatisfied_dependencies"]
            if u["package"] == "sshd"
        ]
        assert len(sshd_viols) == 1, "sshd should have exactly 1 violation"
        v = sshd_viols[0]
        assert "libnet" in v["dependency"]
        assert v["installed_version"] == "2.9.0"

    def test_monitor_libnet(self, report):
        monitor_viols = [
            u for u in report["unsatisfied_dependencies"]
            if u["package"] == "monitor"
        ]
        assert len(monitor_viols) == 1, "monitor should have exactly 1 violation"
        v = monitor_viols[0]
        assert "libnet" in v["dependency"]
        assert v["installed_version"] == "2.9.0"

    def test_legacy_app_dbengine(self, report):
        la_viols = [
            u for u in report["unsatisfied_dependencies"]
            if u["package"] == "legacy-app"
        ]
        assert len(la_viols) == 1, "legacy-app should have exactly 1 violation"
        v = la_viols[0]
        assert "dbengine" in v["dependency"]
        assert "<=" in v["dependency"] or "<" in v["dependency"], (
            "legacy-app violation should be an upper-bound constraint on dbengine"
        )
        assert v["installed_version"] == "5.0.0"

    def test_nettools_libpcap(self, report):
        nt_viols = [
            u for u in report["unsatisfied_dependencies"]
            if u["package"] == "nettools"
        ]
        assert len(nt_viols) == 1, "nettools should have exactly 1 violation"
        v = nt_viols[0]
        assert "libpcap" in v["dependency"]
        assert v["installed_version"] is None, (
            "libpcap is not installed, installed_version should be null"
        )

    def test_no_false_positives(self, report):
        violating_pkgs = {u["package"] for u in report["unsatisfied_dependencies"]}
        expected_pkgs = {"httpd", "sshd", "monitor", "legacy-app", "nettools"}
        assert violating_pkgs == expected_pkgs, (
            f"Unexpected packages with violations: {violating_pkgs - expected_pkgs}"
        )


class TestDependencyCycles:
    def test_plugin_cycle_detected(self, report):
        cycles = report["dependency_cycles"]
        assert len(cycles) >= 1, "Should detect at least one cycle"
        cycle_sets = [set(c) for c in cycles]
        expected_cycle = {"plugin-a", "plugin-b", "plugin-c"}
        assert expected_cycle in cycle_sets, (
            f"Should detect cycle among plugin-a/b/c, got {cycle_sets}"
        )

    def test_cycle_completeness(self, report):
        cycles = report["dependency_cycles"]
        all_cycle_members = set()
        for c in cycles:
            all_cycle_members.update(c)
        assert "plugin-a" in all_cycle_members
        assert "plugin-b" in all_cycle_members
        assert "plugin-c" in all_cycle_members

    def test_no_spurious_cycles(self, report):
        cycles = report["dependency_cycles"]
        all_cycle_members = set()
        for c in cycles:
            all_cycle_members.update(c)
        non_cyclic = {"libcore", "libcrypto", "libnet", "libui", "libdata",
                      "httpd", "sshd", "dbengine", "renderer", "webapp",
                      "monitor", "backup", "cli-tools", "libcompat",
                      "legacy-app", "nettools", "oldutil", "legacy-driver"}
        false_pos = all_cycle_members & non_cyclic
        assert false_pos == set(), f"Spurious cycle members: {false_pos}"


class TestFileConflicts:
    def test_libssl_compat_conflict(self, report):
        conflicts = report["file_conflicts"]
        conflict_map = {}
        for c in conflicts:
            conflict_map[c["path"]] = set(c["owners"])
        assert "/usr/lib/libssl_compat.so" in conflict_map, (
            "Should detect conflict on /usr/lib/libssl_compat.so"
        )
        assert conflict_map["/usr/lib/libssl_compat.so"] == {
            "libcrypto", "libcompat"
        }

    def test_doc_readme_conflict(self, report):
        conflicts = report["file_conflicts"]
        conflict_map = {}
        for c in conflicts:
            conflict_map[c["path"]] = set(c["owners"])
        assert "/usr/share/doc/README" in conflict_map, (
            "Should detect conflict on /usr/share/doc/README"
        )
        assert conflict_map["/usr/share/doc/README"] == {
            "cli-tools", "monitor"
        }

    def test_count(self, report):
        assert len(report["file_conflicts"]) == 2, (
            f"Expected exactly 2 file conflicts, got {len(report['file_conflicts'])}"
        )


class TestOrphanedPackages:
    def test_orphans_detected(self, report):
        orphans = set(report["orphaned_packages"])
        assert orphans == {"oldutil", "legacy-driver"}, (
            f"Expected orphans: oldutil, legacy-driver. Got: {orphans}"
        )

    def test_count(self, report):
        assert len(report["orphaned_packages"]) == 2
