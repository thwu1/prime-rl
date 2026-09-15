
import json
import os
import re
import pytest

REPORT_PATH = "/app/output/report.json"


@pytest.fixture(scope="module")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ── Package Discovery ────────────────────────────────────────────────────────

class TestPackageDiscovery:
    def test_package_count(self, report):
        """12 PKGBUILDs should produce exactly 17 packages (4 split bases + 8 single)."""
        assert len(report["packages"]) == 17

    def test_package_names(self, report):
        expected = {
            "libcore",
            "datastore-server", "datastore-lib", "datastore-tools",
            "altdb-server", "altdb-lib",
            "netstack", "libnet",
            "webapp", "webapp-api",
            "monitor", "cache-mgr", "auth-svc",
            "plugin-host", "ext-loader",
            "log-aggregator", "scheduler",
        }
        assert set(report["packages"].keys()) == expected

    def test_split_base_datastore(self, report):
        for pkg in ("datastore-server", "datastore-lib", "datastore-tools"):
            assert report["packages"][pkg]["base"] == "datastore"

    def test_split_base_altdb(self, report):
        for pkg in ("altdb-server", "altdb-lib"):
            assert report["packages"][pkg]["base"] == "altdb"

    def test_split_base_netstack(self, report):
        for pkg in ("netstack", "libnet"):
            assert report["packages"][pkg]["base"] == "netstack"

    def test_split_base_webapp(self, report):
        for pkg in ("webapp", "webapp-api"):
            assert report["packages"][pkg]["base"] == "webapp"

    def test_simple_package_bases(self, report):
        for pkg in ("libcore", "monitor", "cache-mgr", "auth-svc",
                     "plugin-host", "ext-loader", "log-aggregator", "scheduler"):
            assert report["packages"][pkg]["base"] == pkg


# ── Version Strings ──────────────────────────────────────────────────────────

class TestVersions:
    def test_epoch_libcore(self, report):
        assert report["packages"]["libcore"]["version"] == "1:2.5.0-1"

    def test_epoch_datastore(self, report):
        for pkg in ("datastore-server", "datastore-lib", "datastore-tools"):
            assert report["packages"][pkg]["version"] == "1:3.2.0-1"

    def test_no_epoch_altdb(self, report):
        for pkg in ("altdb-server", "altdb-lib"):
            assert report["packages"][pkg]["version"] == "14.1-1"

    def test_no_epoch_netstack(self, report):
        for pkg in ("netstack", "libnet"):
            assert report["packages"][pkg]["version"] == "4.0.0-1"

    def test_epoch_webapp(self, report):
        for pkg in ("webapp", "webapp-api"):
            assert report["packages"][pkg]["version"] == "2:5.0.1-1"

    def test_no_epoch_monitor(self, report):
        assert report["packages"]["monitor"]["version"] == "1.8.0-1"

    def test_epoch_cache_mgr(self, report):
        assert report["packages"]["cache-mgr"]["version"] == "3:1.0.0-1"

    def test_no_epoch_simple(self, report):
        assert report["packages"]["auth-svc"]["version"] == "2.0.0-1"
        assert report["packages"]["plugin-host"]["version"] == "1.0.0-1"
        assert report["packages"]["ext-loader"]["version"] == "1.0.0-1"

    def test_no_epoch_log_aggregator(self, report):
        assert report["packages"]["log-aggregator"]["version"] == "2.3.1-1"

    def test_no_epoch_scheduler(self, report):
        assert report["packages"]["scheduler"]["version"] == "3.1.0-2"


# ── Dependency Parsing ───────────────────────────────────────────────────────

class TestDependencies:
    def test_libcore_no_deps(self, report):
        assert report["packages"]["libcore"]["depends"] == []

    def test_datastore_lib_deps(self, report):
        assert "libcore" in report["packages"]["datastore-lib"]["depends"]

    def test_datastore_tools_variable_subst(self, report):
        """depends=("${pkgbase}-lib") must resolve to datastore-lib."""
        assert "datastore-lib" in report["packages"]["datastore-tools"]["depends"]

    def test_datastore_server_multiline_variable_subst(self, report):
        """Multi-line depends with ${pkgbase} substitution."""
        deps = report["packages"]["datastore-server"]["depends"]
        assert "datastore-lib" in deps
        assert "datastore-tools" in deps

    def test_webapp_api_virtual_dep(self, report):
        deps = report["packages"]["webapp-api"]["depends"]
        assert any("dbclient" in d for d in deps)

    def test_monitor_versioned_dep(self, report):
        deps = report["packages"]["monitor"]["depends"]
        assert any("webapp-api" in d and "5.0" in d for d in deps)
        assert "libnet" in deps

    def test_cache_mgr_deps(self, report):
        deps = report["packages"]["cache-mgr"]["depends"]
        assert any("dbclient" in d for d in deps)
        assert "libnet" in deps

    def test_auth_svc_deps(self, report):
        deps = report["packages"]["auth-svc"]["depends"]
        assert "webapp-api" in deps
        assert "cache-mgr" in deps

    def test_plugin_host_deps(self, report):
        deps = report["packages"]["plugin-host"]["depends"]
        assert "auth-svc" in deps
        assert any("ext-api" in d for d in deps)

    def test_ext_loader_deps(self, report):
        deps = report["packages"]["ext-loader"]["depends"]
        assert any("plug-api" in d for d in deps)

    def test_log_aggregator_deps(self, report):
        deps = report["packages"]["log-aggregator"]["depends"]
        assert "monitor" in deps
        assert "libnet" in deps

    def test_scheduler_deps(self, report):
        deps = report["packages"]["scheduler"]["depends"]
        assert "auth-svc" in deps
        assert any("log-api" in d for d in deps)


# ── Provides / Variable Substitution ─────────────────────────────────────────

class TestProviders:
    def test_providers_key_exists(self, report):
        assert "providers" in report

    def test_core_api(self, report):
        assert "libcore" in report["providers"]["core-api"]

    def test_dbclient_both_providers(self, report):
        assert set(report["providers"]["dbclient"]) == {
            "datastore-lib", "altdb-lib"
        }

    def test_network_tools(self, report):
        assert "netstack" in report["providers"]["network-tools"]

    def test_health_check(self, report):
        assert "monitor" in report["providers"]["health-check"]

    def test_auth_backend(self, report):
        assert "auth-svc" in report["providers"]["auth-backend"]

    def test_plug_api(self, report):
        assert "plugin-host" in report["providers"]["plug-api"]

    def test_ext_api(self, report):
        assert "ext-loader" in report["providers"]["ext-api"]

    def test_log_api(self, report):
        assert "log-aggregator" in report["providers"]["log-api"]

    def test_cron_backend(self, report):
        assert "scheduler" in report["providers"]["cron-backend"]

    def test_provides_version_from_pkgver_subst(self, report):
        """provides=("dbclient=${pkgver}") must yield dbclient=3.2.0."""
        prov = report["packages"]["datastore-lib"]["provides"]
        assert "dbclient=3.2.0" in prov

    def test_provides_version_altdb(self, report):
        """provides=("dbclient=${pkgver}") in altdb must yield dbclient=14.1."""
        prov = report["packages"]["altdb-lib"]["provides"]
        assert "dbclient=14.1" in prov

    def test_provides_version_monitor(self, report):
        """provides=("health-check=${pkgver}") must yield health-check=1.8.0."""
        prov = report["packages"]["monitor"]["provides"]
        assert "health-check=1.8.0" in prov

    def test_provides_bash_param_expansion(self, report):
        """provides=("log-api=${_majorver}.0") where _majorver=${pkgver%%.*}
        must expand to log-api=2.0 (pkgver=2.3.1, %%.*  strips to 2)."""
        prov = report["packages"]["log-aggregator"]["provides"]
        assert "log-api=2.0" in prov

    def test_provides_scheduler(self, report):
        prov = report["packages"]["scheduler"]["provides"]
        assert "cron-backend=3.1.0" in prov


# ── Conflicts ────────────────────────────────────────────────────────────────

class TestConflicts:
    def test_conflict_groups_key_exists(self, report):
        assert "conflict_groups" in report

    def test_server_conflict(self, report):
        groups = [set(g) for g in report["conflict_groups"]]
        assert {"datastore-server", "altdb-server"} in groups

    def test_lib_conflict(self, report):
        groups = [set(g) for g in report["conflict_groups"]]
        assert {"datastore-lib", "altdb-lib"} in groups

    def test_exactly_two_conflict_groups(self, report):
        assert len(report["conflict_groups"]) == 2


# ── Circular Dependencies ───────────────────────────────────────────────────

class TestCircularDeps:
    def test_circular_key_exists(self, report):
        assert "circular_dependencies" in report

    def test_plugin_ext_cycle(self, report):
        cycles = [set(c) for c in report["circular_dependencies"]]
        assert {"plugin-host", "ext-loader"} in cycles

    def test_exactly_one_cycle(self, report):
        assert len(report["circular_dependencies"]) == 1


# ── Build Order ──────────────────────────────────────────────────────────────

class TestBuildOrder:
    def test_build_order_key_exists(self, report):
        assert "build_order" in report

    def test_cyclic_excluded(self, report):
        order = report["build_order"]
        assert "plugin-host" not in order
        assert "ext-loader" not in order

    def test_all_non_cyclic_present(self, report):
        expected = {
            "libcore",
            "datastore-server", "datastore-lib", "datastore-tools",
            "altdb-server", "altdb-lib",
            "netstack", "libnet",
            "webapp", "webapp-api",
            "monitor", "cache-mgr", "auth-svc",
            "log-aggregator", "scheduler",
        }
        assert set(report["build_order"]) == expected

    def test_libcore_is_first(self, report):
        assert report["build_order"][0] == "libcore"

    def test_datastore_internal_order(self, report):
        order = report["build_order"]
        assert order.index("datastore-lib") < order.index("datastore-tools")
        assert order.index("datastore-tools") < order.index("datastore-server")

    def test_altdb_internal_order(self, report):
        order = report["build_order"]
        assert order.index("altdb-lib") < order.index("altdb-server")

    def test_netstack_internal_order(self, report):
        order = report["build_order"]
        assert order.index("libnet") < order.index("netstack")

    def test_webapp_internal_order(self, report):
        order = report["build_order"]
        assert order.index("webapp-api") < order.index("webapp")

    def test_auth_svc_after_deps(self, report):
        order = report["build_order"]
        assert order.index("webapp-api") < order.index("auth-svc")
        assert order.index("cache-mgr") < order.index("auth-svc")

    def test_scheduler_after_deps(self, report):
        order = report["build_order"]
        assert order.index("auth-svc") < order.index("scheduler")
        assert order.index("log-aggregator") < order.index("scheduler")

    def test_log_aggregator_after_deps(self, report):
        order = report["build_order"]
        assert order.index("monitor") < order.index("log-aggregator")
        assert order.index("libnet") < order.index("log-aggregator")

    def test_topological_validity(self, report):
        """For every package, at least one provider of each dep appears earlier."""
        order = report["build_order"]
        packages = report["packages"]
        providers = report["providers"]
        position = {pkg: i for i, pkg in enumerate(order)}

        for pkg in order:
            for dep_str in packages[pkg]["depends"]:
                dep_n = re.split(r"[><=]", dep_str)[0]

                satisfiers = set()
                if dep_n in position:
                    satisfiers.add(dep_n)
                if dep_n in providers:
                    for p in providers[dep_n]:
                        if p in position:
                            satisfiers.add(p)

                assert satisfiers, (
                    f"{pkg} depends on '{dep_n}' but no satisfier is in "
                    f"the build order"
                )
                earliest = min(position[s] for s in satisfiers)
                assert earliest < position[pkg], (
                    f"{pkg} (pos {position[pkg]}) depends on {dep_n}, "
                    f"but earliest satisfier is at pos {earliest}"
                )

    def test_build_order_exact(self, report):
        """Verify the exact build order with alphabetical tiebreaking."""
        expected = [
            "libcore", "altdb-lib", "altdb-server", "datastore-lib",
            "datastore-tools", "datastore-server", "libnet", "cache-mgr",
            "netstack", "webapp-api", "auth-svc", "monitor",
            "log-aggregator", "scheduler", "webapp",
        ]
        assert report["build_order"] == expected


# ── Vercmp ───────────────────────────────────────────────────────────────────

class TestVercmp:
    def test_vercmp_results_exist(self, report):
        assert "vercmp_results" in report
        assert len(report["vercmp_results"]) == 7

    def test_epoch_beats_higher_version(self, report):
        """1:2.5.0-1 vs 3.2.0-1: epoch 1 > 0."""
        assert report["vercmp_results"][0] == ["1:2.5.0-1", "3.2.0-1", 1]

    def test_numeric_comparison(self, report):
        """14.1 vs 3.2.0: first segment 14 > 3."""
        assert report["vercmp_results"][1] == ["14.1", "3.2.0", 1]

    def test_epoch_beats_no_epoch(self, report):
        """2:5.0.1-1 vs 5.0: epoch 2 > 0."""
        assert report["vercmp_results"][2] == ["2:5.0.1-1", "5.0", 1]

    def test_extra_segment_wins(self, report):
        """1.0.0 vs 1.0: extra trailing segment wins."""
        assert report["vercmp_results"][3] == ["1.0.0", "1.0", 1]

    def test_higher_epoch_beats_higher_version(self, report):
        """3:1.0.0-1 vs 2:99.99-1: epoch 3 > 2 regardless of version."""
        assert report["vercmp_results"][4] == ["3:1.0.0-1", "2:99.99-1", 1]

    def test_alpha_segment_ordering(self, report):
        """1.0.0alpha vs 1.0.0beta: alpha < beta lexicographically."""
        assert report["vercmp_results"][5] == ["1.0.0alpha", "1.0.0beta", -1]

    def test_missing_segment_loses(self, report):
        """1.0.0 vs 1.0.0a: shorter version loses."""
        assert report["vercmp_results"][6] == ["1.0.0", "1.0.0a", -1]


# ── Install Simulation ──────────────────────────────────────────────────────

class TestInstallSimulation:
    def test_simulation_exists(self, report):
        assert "install_simulation" in report

    def test_install_set_size(self, report):
        assert len(report["install_simulation"]["install_order"]) == 10

    def test_install_order_exact(self, report):
        """Exact install order with alphabetical tiebreaking."""
        expected = [
            "libcore", "altdb-lib", "libnet", "cache-mgr", "webapp-api",
            "auth-svc", "monitor", "log-aggregator", "scheduler", "webapp",
        ]
        assert report["install_simulation"]["install_order"] == expected

    def test_provider_selection_dbclient(self, report):
        """dbclient has two providers; altdb-lib provides 14.1 > 3.2.0."""
        assert report["install_simulation"]["provider_selections"]["dbclient"] == "altdb-lib"

    def test_provider_selection_log_api(self, report):
        """log-api has single provider log-aggregator."""
        assert report["install_simulation"]["provider_selections"]["log-api"] == "log-aggregator"

    def test_no_unresolved_constraints(self, report):
        assert report["install_simulation"]["unresolved"] == []

    def test_conflicting_packages_excluded(self, report):
        """datastore-lib must NOT be in install set (conflicts with altdb-lib)."""
        assert "datastore-lib" not in report["install_simulation"]["install_order"]

    def test_unneeded_packages_excluded(self, report):
        """netstack, altdb-server etc. not needed by targets."""
        order = report["install_simulation"]["install_order"]
        assert "netstack" not in order
        assert "altdb-server" not in order
        assert "datastore-server" not in order
        assert "datastore-tools" not in order


# ── SRCINFO Generation ───────────────────────────────────────────────────────

class TestSrcinfo:
    def test_srcinfo_files_exist(self):
        for pkgbase in ["libcore", "datastore", "altdb", "netstack", "webapp",
                        "monitor", "cache-mgr", "auth-svc", "plugin-host",
                        "ext-loader", "log-aggregator", "scheduler"]:
            path = f"/app/output/srcinfo/{pkgbase}.SRCINFO"
            assert os.path.exists(path), f"Missing SRCINFO: {path}"

    def test_srcinfo_tab_indentation(self):
        with open("/app/output/srcinfo/libcore.SRCINFO") as f:
            content = f.read()
        lines = content.strip().split("\n")
        assert lines[0] == "pkgbase = libcore"
        # All field lines must be tab-indented
        for line in lines[1:]:
            if line and not line.startswith("pkgname"):
                assert line.startswith("\t"), f"Not tab-indented: {line!r}"

    def test_srcinfo_variable_expansion_source(self):
        """Source URLs must have ${pkgbase} and ${pkgver} expanded."""
        with open("/app/output/srcinfo/datastore.SRCINFO") as f:
            content = f.read()
        assert "https://github.com/example/datastore/archive/v3.2.0.tar.gz" in content
        assert "${" not in content

    def test_srcinfo_bash_param_expansion_majorver(self):
        """log-aggregator: ${pkgver%%.*} must expand to 2, so provides = log-api=2.0."""
        with open("/app/output/srcinfo/log-aggregator.SRCINFO") as f:
            content = f.read()
        assert "\tprovides = log-api=2.0" in content

    def test_srcinfo_bash_param_expansion_dashver(self):
        """scheduler: ${pkgver//./-} must expand to 3-1-0 in the source URL."""
        with open("/app/output/srcinfo/scheduler.SRCINFO") as f:
            content = f.read()
        assert "v3-1-0" in content
        assert "${" not in content

    def test_srcinfo_split_pkg_ordering(self):
        """Package sections must appear in pkgname=() array order."""
        with open("/app/output/srcinfo/datastore.SRCINFO") as f:
            content = f.read()
        # pkgname=('datastore-server' 'datastore-lib' 'datastore-tools')
        pos_server = content.index("pkgname = datastore-server")
        pos_lib = content.index("pkgname = datastore-lib")
        pos_tools = content.index("pkgname = datastore-tools")
        assert pos_server < pos_lib < pos_tools

    def test_srcinfo_split_pkg_no_global_depends(self):
        """For split packages, global section must NOT contain depends
        (since depends is only defined in package_*() functions)."""
        with open("/app/output/srcinfo/datastore.SRCINFO") as f:
            content = f.read()
        global_section = content.split("pkgname =")[0]
        assert "\tdepends" not in global_section

    def test_srcinfo_split_pkg_overrides(self):
        """Split package sections should contain per-package overrides."""
        with open("/app/output/srcinfo/datastore.SRCINFO") as f:
            content = f.read()
        # Find the datastore-lib section
        lib_start = content.index("pkgname = datastore-lib")
        # Find the next section
        tools_start = content.index("pkgname = datastore-tools")
        lib_section = content[lib_start:tools_start]
        assert "\tdepends = libcore" in lib_section
        assert "\tprovides = dbclient=3.2.0" in lib_section
        assert "\tconflicts = altdb-lib" in lib_section

    def test_srcinfo_epoch_present(self):
        with open("/app/output/srcinfo/libcore.SRCINFO") as f:
            content = f.read()
        assert "\tepoch = 1" in content

    def test_srcinfo_field_order_global(self):
        """Verify standard field ordering in the global section."""
        with open("/app/output/srcinfo/monitor.SRCINFO") as f:
            content = f.read()
        global_section = content.split("pkgname =")[0]
        lines = global_section.strip().split("\n")
        fields_seen = []
        for line in lines:
            if line.startswith("\t"):
                field = line.strip().split(" = ")[0]
                if field not in fields_seen:
                    fields_seen.append(field)
        # Expected order per makepkg --printsrcinfo
        expected_order = ["pkgdesc", "pkgver", "pkgrel", "url", "arch", "license",
                         "makedepends", "depends", "provides", "source", "sha256sums"]
        actual = [f for f in fields_seen if f in expected_order]
        assert actual == [f for f in expected_order if f in actual], (
            f"Field order mismatch: got {actual}"
        )

    def test_srcinfo_single_pkg_section_minimal(self):
        """For single-package PKGBUILDs, pkgname section has no extra fields."""
        with open("/app/output/srcinfo/libcore.SRCINFO") as f:
            content = f.read()
        pkg_start = content.index("pkgname = libcore")
        after = content[pkg_start + len("pkgname = libcore"):].strip()
        # After pkgname line, there should be nothing (or end of file)
        assert after == "", f"Single pkg should have no override fields, got: {after!r}"


# ── Graphviz SVG ─────────────────────────────────────────────────────────────

class TestGraphviz:
    def test_svg_exists(self):
        assert os.path.exists("/app/output/deps.svg"), "deps.svg not found"

    def test_svg_is_valid(self):
        with open("/app/output/deps.svg") as f:
            content = f.read()
        assert "<svg" in content, "Not a valid SVG file"

    def test_svg_contains_packages(self):
        with open("/app/output/deps.svg") as f:
            content = f.read()
        # graphviz encodes '-' as '&#45;' in SVG, so check both forms
        for pkg in ["libcore", "scheduler", "log"]:
            assert pkg in content, f"Package {pkg} not in SVG"
