
import json
import os
import sqlite3
import subprocess
import pytest


@pytest.fixture(scope="module")
def pipeline():
    """Run the audit pipeline and return the result."""
    result = subprocess.run(
        ["bash", "/app/audit-pipeline.sh"],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"Pipeline failed (rc={result.returncode}):\n{result.stderr}"
    return result


@pytest.fixture(scope="module")
def db(pipeline):
    """SQLite database connection."""
    conn = sqlite3.connect("/app/repo.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def audit(pipeline):
    """Parsed audit JSON report."""
    with open("/app/audit.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dot_content(pipeline):
    """DOT graph file content."""
    with open("/app/depgraph.dot") as f:
        return f.read()


# ===========================================
# Output existence
# ===========================================

class TestOutputFiles:
    def test_repo_db_exists(self, pipeline):
        assert os.path.exists("/app/repo.db")

    def test_dot_exists(self, pipeline):
        assert os.path.exists("/app/depgraph.dot")

    def test_svg_exists(self, pipeline):
        assert os.path.exists("/app/depgraph.svg")

    def test_json_exists(self, pipeline):
        assert os.path.exists("/app/audit.json")


# ===========================================
# SQLite schema
# ===========================================

class TestSQLiteSchema:
    def test_packages_table(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='packages'"
        ).fetchone()
        assert row is not None

    def test_package_arch_table(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='package_arch'"
        ).fetchone()
        assert row is not None

    def test_depends_table(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='depends'"
        ).fetchone()
        assert row is not None

    def test_provides_table(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='provides'"
        ).fetchone()
        assert row is not None

    def test_conflicts_table(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conflicts'"
        ).fetchone()
        assert row is not None


# ===========================================
# SQLite data — basic
# ===========================================

class TestSQLitePackages:
    def test_package_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM packages").fetchone()[0]
        assert count == 16

    def test_all_packages_present(self, db):
        names = {row[0] for row in db.execute("SELECT name FROM packages")}
        expected = {
            "baselib", "baselib-git",
            "datastore", "datastore-libs", "datastore-client",
            "webapp", "monitor", "dashboard", "toolkit", "alerter",
            "net-core", "net-tls", "net-http",
            "appfw", "appfw-runtime", "appfw-devtools",
        }
        assert names == expected

    def test_baselib_fields(self, db):
        r = db.execute(
            "SELECT pkgver, pkgrel, epoch, full_version FROM packages WHERE name='baselib'"
        ).fetchone()
        assert r["pkgver"] == "2.1.0"
        assert r["pkgrel"] == "1"
        assert r["epoch"] == 0
        assert r["full_version"] == "2.1.0-1"

    def test_datastore_epoch(self, db):
        r = db.execute(
            "SELECT epoch, full_version FROM packages WHERE name='datastore'"
        ).fetchone()
        assert r["epoch"] == 1
        assert r["full_version"] == "1:5.4.0-2"

    def test_netstack_epoch(self, db):
        r = db.execute(
            "SELECT epoch, full_version FROM packages WHERE name='net-core'"
        ).fetchone()
        assert r["epoch"] == 2
        assert r["full_version"] == "2:4.0.2-1"

    def test_baselib_git_version(self, db):
        r = db.execute(
            "SELECT pkgver, full_version FROM packages WHERE name='baselib-git'"
        ).fetchone()
        assert r["pkgver"] == "2.2.0.r3.gabc1234"
        assert r["full_version"] == "2.2.0.r3.gabc1234-1"

    def test_split_pkgbase_datastore(self, db):
        for name in ("datastore", "datastore-libs", "datastore-client"):
            r = db.execute(
                "SELECT pkgbase FROM packages WHERE name=?", (name,)
            ).fetchone()
            assert r["pkgbase"] == "datastore"

    def test_split_pkgbase_netstack(self, db):
        for name in ("net-core", "net-tls", "net-http"):
            r = db.execute(
                "SELECT pkgbase FROM packages WHERE name=?", (name,)
            ).fetchone()
            assert r["pkgbase"] == "netstack"

    def test_split_pkgbase_appframework(self, db):
        for name in ("appfw", "appfw-runtime", "appfw-devtools"):
            r = db.execute(
                "SELECT pkgbase FROM packages WHERE name=?", (name,)
            ).fetchone()
            assert r["pkgbase"] == "appframework"


# ===========================================
# Computed-variable packages (require bash eval)
# ===========================================

class TestBashEvalPackages:
    """Packages that use computed variables / eval+declare-f and cannot be regex-parsed."""

    def test_net_tls_depends_on_prefix_core(self, db):
        """depends=('${_prefix}-core' ...) must resolve to 'net-core'."""
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='net-tls' AND dep_type='depends'"
        )}
        assert "net-core" in deps

    def test_net_http_depends_on_prefix_tls(self, db):
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='net-http' AND dep_type='depends'"
        )}
        assert "net-tls" in deps

    def test_net_core_provides_libnetcore(self, db):
        provs = {(r[0], r[1]) for r in db.execute(
            "SELECT provided_name, provided_version FROM provides WHERE package_name='net-core'"
        )}
        assert ("libnetcore", "4.0.2") in provs

    def test_net_http_provides_http_client(self, db):
        provs = {(r[0], r[1]) for r in db.execute(
            "SELECT provided_name, provided_version FROM provides WHERE package_name='net-http'"
        )}
        assert ("http-client", "4.0.2") in provs

    def test_appfw_depends_on_group_runtime(self, db):
        """depends=('${_group}-runtime' ...) must resolve to 'appfw-runtime'."""
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='appfw' AND dep_type='depends'"
        )}
        assert "appfw-runtime" in deps
        assert "appfw-devtools" in deps

    def test_appfw_runtime_depends(self, db):
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='appfw-runtime' AND dep_type='depends'"
        )}
        assert "net-http" in deps
        assert "baselib" in deps
        assert "datastore-libs" in deps

    def test_appfw_runtime_provides_with_group_var(self, db):
        """provides=('${_group}-runtime=${pkgver}') must resolve to 'appfw-runtime=2.5.0'."""
        provs = {(r[0], r[1]) for r in db.execute(
            "SELECT provided_name, provided_version FROM provides WHERE package_name='appfw-runtime'"
        )}
        assert ("appfw-runtime", "2.5.0") in provs

    def test_appfw_devtools_depends_on_group_runtime(self, db):
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='appfw-devtools' AND dep_type='depends'"
        )}
        assert "appfw-runtime" in deps

    def test_appfw_pkgdesc_expanded_apiver(self, db):
        """pkgdesc='Full application framework (v${_apiver})' must contain 'v2'."""
        r = db.execute("SELECT pkgdesc FROM packages WHERE name='appfw'").fetchone()
        assert "v2" in r[0]

    def test_appfw_runtime_pkgdesc_expanded(self, db):
        r = db.execute("SELECT pkgdesc FROM packages WHERE name='appfw-runtime'").fetchone()
        assert "API v2" in r[0]


# ===========================================
# Existing split-package and variable expansion tests
# ===========================================

class TestSplitPackageDatastore:
    def test_libs_depends(self, db):
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='datastore-libs' AND dep_type='depends'"
        )}
        assert {"glibc", "openssl", "zlib"} <= deps

    def test_client_depends(self, db):
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='datastore-client' AND dep_type='depends'"
        )}
        assert "datastore-libs" in deps
        assert "baselib" in deps

    def test_server_depends_on_client(self, db):
        deps = {r[0] for r in db.execute(
            "SELECT dep_name FROM depends WHERE package_name='datastore' AND dep_type='depends'"
        )}
        assert "datastore-client" in deps
        assert "datastore-libs" in deps

    def test_libs_provides_expanded_var(self, db):
        """provides=('libdatastore=${pkgver}') should expand to libdatastore=5.4.0."""
        provs = {(r[0], r[1]) for r in db.execute(
            "SELECT provided_name, provided_version FROM provides WHERE package_name='datastore-libs'"
        )}
        assert ("libdatastore", "5.4.0") in provs

    def test_server_description(self, db):
        r = db.execute("SELECT pkgdesc FROM packages WHERE name='datastore'").fetchone()
        desc = r[0].lower()
        assert "server" in desc or "engine" in desc


# ===========================================
# Provides / conflicts in database
# ===========================================

class TestDBProvidesConflicts:
    def test_baselib_git_provides(self, db):
        provs = {(r[0], r[1]) for r in db.execute(
            "SELECT provided_name, provided_version FROM provides WHERE package_name='baselib-git'"
        )}
        assert ("baselib", "2.2.0") in provs

    def test_baselib_git_conflicts(self, db):
        confs = {r[0] for r in db.execute(
            "SELECT conflict_name FROM conflicts WHERE package_name='baselib-git'"
        )}
        assert "baselib" in confs

    def test_alerter_conflicts_dashboard(self, db):
        confs = {r[0] for r in db.execute(
            "SELECT conflict_name FROM conflicts WHERE package_name='alerter'"
        )}
        assert "dashboard" in confs

    def test_monitor_provides_metrics(self, db):
        provs = {r[0] for r in db.execute(
            "SELECT provided_name FROM provides WHERE package_name='monitor'"
        )}
        assert "metrics-collector" in provs


# ===========================================
# Dependency graph
# ===========================================

class TestDependencyGraph:
    def test_svg_valid(self, pipeline):
        with open("/app/depgraph.svg") as f:
            content = f.read()
        assert "<svg" in content
        assert "</svg>" in content

    def test_dot_has_packages(self, dot_content):
        for pkg in ("baselib", "net-core", "appfw-runtime", "datastore-libs", "toolkit"):
            assert pkg in dot_content

    def test_dot_has_split_clusters(self, dot_content):
        assert "subgraph cluster_datastore" in dot_content
        assert "subgraph cluster_netstack" in dot_content
        assert "subgraph cluster_appframework" in dot_content

    def test_dot_has_conflict_edges(self, dot_content):
        assert "color=red" in dot_content

    def test_dot_has_unsatisfiable_shape(self, dot_content):
        assert "doubleoctagon" in dot_content

    def test_dot_has_dashed_makedeps(self, dot_content):
        assert "style=dashed" in dot_content


# ===========================================
# Audit JSON — top-level
# ===========================================

class TestAuditStructure:
    def test_package_count(self, audit):
        assert audit["package_count"] == 16

    def test_pkgbase_count(self, audit):
        assert audit["pkgbase_count"] == 10

    def test_all_packages_present(self, audit):
        expected = {
            "baselib", "baselib-git",
            "datastore", "datastore-libs", "datastore-client",
            "webapp", "monitor", "dashboard", "toolkit", "alerter",
            "net-core", "net-tls", "net-http",
            "appfw", "appfw-runtime", "appfw-devtools",
        }
        assert set(audit["packages"].keys()) == expected

    def test_has_build_order(self, audit):
        assert isinstance(audit["build_order"], list)

    def test_has_issues(self, audit):
        assert isinstance(audit["issues"], list)

    def test_has_installable_groups(self, audit):
        assert isinstance(audit["installable_groups"], list)


# ===========================================
# Build order
# ===========================================

class TestBuildOrder:
    def test_nonempty(self, audit):
        assert len(audit["build_order"]) > 0

    def test_toolkit_excluded(self, audit):
        assert "toolkit" not in audit["build_order"]

    def test_uses_pkgbases_not_subpackages(self, audit):
        for name in ("datastore-libs", "datastore-client",
                      "net-core", "net-tls", "net-http",
                      "appfw", "appfw-runtime", "appfw-devtools"):
            assert name not in audit["build_order"]

    def test_expected_pkgbases(self, audit):
        expected = {"baselib", "baselib-git", "datastore", "webapp",
                    "monitor", "dashboard", "alerter", "netstack", "appframework"}
        assert set(audit["build_order"]) == expected

    def test_baselib_before_datastore(self, audit):
        order = audit["build_order"]
        base_idxs = [i for i, b in enumerate(order) if b in ("baselib", "baselib-git")]
        assert min(base_idxs) < order.index("datastore")

    def test_datastore_before_webapp(self, audit):
        order = audit["build_order"]
        assert order.index("datastore") < order.index("webapp")

    def test_webapp_before_monitor(self, audit):
        order = audit["build_order"]
        assert order.index("webapp") < order.index("monitor")

    def test_monitor_before_dashboard(self, audit):
        order = audit["build_order"]
        assert order.index("monitor") < order.index("dashboard")

    def test_monitor_before_alerter(self, audit):
        order = audit["build_order"]
        assert order.index("monitor") < order.index("alerter")

    def test_netstack_before_appframework(self, audit):
        order = audit["build_order"]
        assert order.index("netstack") < order.index("appframework")

    def test_baselib_before_netstack(self, audit):
        order = audit["build_order"]
        base_idxs = [i for i, b in enumerate(order) if b in ("baselib", "baselib-git")]
        assert min(base_idxs) < order.index("netstack")


# ===========================================
# Conflict detection
# ===========================================

class TestConflicts:
    def _conflict_pairs(self, audit):
        cs = [i for i in audit["issues"] if i["type"] == "CONFLICT"]
        return [tuple(sorted(c["packages"])) for c in cs]

    def test_baselib_conflict(self, audit):
        assert ("baselib", "baselib-git") in self._conflict_pairs(audit)

    def test_alerter_dashboard_conflict(self, audit):
        assert ("alerter", "dashboard") in self._conflict_pairs(audit)

    def test_exactly_two_conflicts(self, audit):
        assert len(set(self._conflict_pairs(audit))) == 2


# ===========================================
# Version mismatch
# ===========================================

class TestVersionMismatch:
    def test_toolkit_mismatch(self, audit):
        mismatches = [i for i in audit["issues"] if i["type"] == "VERSION_MISMATCH"]
        toolkit_mm = [m for m in mismatches if m["package"] == "toolkit"]
        assert len(toolkit_mm) >= 1
        assert any("baselib" in m.get("dependency", "") for m in toolkit_mm)

    def test_only_toolkit_has_mismatches(self, audit):
        mismatches = [i for i in audit["issues"] if i["type"] == "VERSION_MISMATCH"]
        pkgs = {m["package"] for m in mismatches}
        assert pkgs == {"toolkit"}, f"Unexpected: {pkgs}"


# ===========================================
# Installable groups
# ===========================================

class TestInstallableGroups:
    def test_exactly_four_groups(self, audit):
        assert len(audit["installable_groups"]) == 4

    def test_each_group_size(self, audit):
        for group in audit["installable_groups"]:
            assert len(group) == 13

    def test_toolkit_excluded(self, audit):
        for group in audit["installable_groups"]:
            assert "toolkit" not in group

    def test_one_baselib_per_group(self, audit):
        for group in audit["installable_groups"]:
            assert not ("baselib" in group and "baselib-git" in group)

    def test_dashboard_alerter_not_together(self, audit):
        for group in audit["installable_groups"]:
            assert not ("dashboard" in group and "alerter" in group)

    def test_no_internal_conflicts(self, audit):
        pkgs = audit["packages"]
        for group in audit["installable_groups"]:
            group_set = set(group)
            for pkg_name in group:
                if pkg_name in pkgs:
                    for conf in pkgs[pkg_name].get("conflicts", []):
                        conf_name = conf.split(">")[0].split("<")[0].split("=")[0]
                        if conf_name != pkg_name:
                            assert conf_name not in group_set, \
                                f"Conflict: {pkg_name} vs {conf_name} in same group"

    def test_core_packages_in_all_groups(self, audit):
        core = {"datastore", "datastore-libs", "datastore-client",
                "webapp", "monitor",
                "net-core", "net-tls", "net-http",
                "appfw", "appfw-runtime", "appfw-devtools"}
        for group in audit["installable_groups"]:
            assert core <= set(group), f"Missing: {core - set(group)}"
