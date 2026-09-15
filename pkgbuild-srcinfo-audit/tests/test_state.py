
import json
import os
import pytest


REPO_DIR = "/app/repo"
RESULTS_DIR = "/app/results"

# All installable package names (including split sub-packages)
ALL_PKGNAMES = [
    "netutils", "datastore", "datastore-libs", "datastore-client",
    "webproxy", "logcollector", "loganalyzer", "appserver",
]

PKG_DIRS = ["netutils", "datastore", "webproxy", "logcollector", "loganalyzer", "appserver"]


def read_srcinfo(pkg_dir):
    """Read and return .SRCINFO content for a package directory."""
    path = os.path.join(REPO_DIR, pkg_dir, ".SRCINFO")
    assert os.path.isfile(path), f".SRCINFO not found at {path}"
    with open(path) as f:
        return f.read()


def srcinfo_lines(content):
    """Return list of stripped-but-tab-preserved lines."""
    return [line.rstrip() for line in content.split("\n") if line.strip()]


def has_field(content, field, value):
    """Check if .SRCINFO contains a tab-indented field = value line."""
    target = f"\t{field} = {value}"
    return target in content


def has_section(content, section_type, name):
    """Check if .SRCINFO contains 'section_type = name' as a non-indented line."""
    target = f"{section_type} = {name}"
    lines = content.split("\n")
    return any(line.strip() == target and not line.startswith("\t") for line in lines)


# ─── .SRCINFO existence ───


class TestSrcinfoExistence:
    @pytest.mark.parametrize("pkg_dir", PKG_DIRS)
    def test_srcinfo_exists(self, pkg_dir):
        path = os.path.join(REPO_DIR, pkg_dir, ".SRCINFO")
        assert os.path.isfile(path), f".SRCINFO missing for {pkg_dir}"


# ─── netutils .SRCINFO ───


class TestSrcinfoNetutils:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_srcinfo("netutils")

    def test_pkgbase(self):
        assert has_section(self.content, "pkgbase", "netutils")

    def test_pkgname(self):
        assert has_section(self.content, "pkgname", "netutils")

    def test_pkgver(self):
        assert has_field(self.content, "pkgver", "2.4.1")

    def test_pkgrel(self):
        assert has_field(self.content, "pkgrel", "3")

    def test_no_epoch(self):
        assert "\tepoch = " not in self.content

    def test_source_url_expanded(self):
        """Variable expansion: ${pkgname} and ${pkgver} must be resolved."""
        assert has_field(
            self.content, "source",
            "https://example.com/releases/netutils-2.4.1.tar.gz"
        )

    def test_source_sysconfig(self):
        assert has_field(self.content, "source", "netutils.sysconfig")

    def test_depends(self):
        assert has_field(self.content, "depends", "openssl")
        assert has_field(self.content, "depends", "curl")
        assert has_field(self.content, "depends", "libpcap")

    def test_makedepends(self):
        assert has_field(self.content, "makedepends", "cmake")
        assert has_field(self.content, "makedepends", "gcc")

    def test_checksum_count(self):
        lines = srcinfo_lines(self.content)
        sha_lines = [l for l in lines if "\tsha256sums = " in l]
        src_lines = [l for l in lines if "\tsource = " in l]
        assert len(sha_lines) == 2
        assert len(src_lines) == 2


# ─── datastore .SRCINFO (split package + brace expansion) ───


class TestSrcinfoDatastore:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_srcinfo("datastore")

    def test_pkgbase(self):
        assert has_section(self.content, "pkgbase", "datastore")

    def test_three_pkgname_sections(self):
        """Split package must have three pkgname sections."""
        assert has_section(self.content, "pkgname", "datastore")
        assert has_section(self.content, "pkgname", "datastore-libs")
        assert has_section(self.content, "pkgname", "datastore-client")

    def test_pkgname_order(self):
        """pkgname sections must appear in the order declared in pkgname array."""
        lines = [l.strip() for l in self.content.split("\n")]
        pkgname_indices = []
        for name in ["datastore", "datastore-libs", "datastore-client"]:
            target = f"pkgname = {name}"
            idx = next((i for i, l in enumerate(lines) if l == target), -1)
            assert idx >= 0, f"pkgname = {name} not found"
            pkgname_indices.append(idx)
        assert pkgname_indices == sorted(pkgname_indices), \
            "pkgname sections not in declared order"

    def test_brace_expansion_source(self):
        """'url'{,.asc} must expand to two source entries."""
        assert has_field(
            self.content, "source",
            "https://example.com/downloads/datastore-5.8.2.tar.gz"
        )
        assert has_field(
            self.content, "source",
            "https://example.com/downloads/datastore-5.8.2.tar.gz.asc"
        )

    def test_four_sources(self):
        lines = srcinfo_lines(self.content)
        src_lines = [l for l in lines if "\tsource = " in l]
        assert len(src_lines) == 4

    def test_four_checksums(self):
        lines = srcinfo_lines(self.content)
        sha_lines = [l for l in lines if "\tsha256sums = " in l]
        assert len(sha_lines) == 4

    def test_validpgpkeys(self):
        assert has_field(
            self.content, "validpgpkeys",
            "ABCD1234ABCD1234ABCD1234ABCD1234ABCD1234"
        )

    def test_datastore_server_depends(self):
        """package_datastore() sets its own depends."""
        # Find the datastore pkgname section and check its depends
        sections = self.content.split("pkgname = ")
        ds_section = None
        for s in sections:
            if s.startswith("datastore\n") and not s.startswith("datastore-"):
                ds_section = s
                break
        assert ds_section is not None
        assert "\tdepends = datastore-libs" in ds_section
        assert "\tdepends = systemd-libs" in ds_section

    def test_datastore_libs_provides(self):
        """package_datastore-libs() provides libdatastore=${pkgver}."""
        sections = self.content.split("pkgname = ")
        libs_section = next((s for s in sections if s.startswith("datastore-libs")), None)
        assert libs_section is not None
        assert "\tprovides = libdatastore=5.8.2" in libs_section

    def test_datastore_libs_conflicts(self):
        sections = self.content.split("pkgname = ")
        libs_section = next((s for s in sections if s.startswith("datastore-libs")), None)
        assert libs_section is not None
        assert "\tconflicts = libdatastore-legacy" in libs_section

    def test_datastore_client_depends(self):
        sections = self.content.split("pkgname = ")
        client_section = next((s for s in sections if s.startswith("datastore-client")), None)
        assert client_section is not None
        assert "\tdepends = datastore-libs" in client_section
        assert "\tdepends = readline" in client_section

    def test_datastore_server_backup(self):
        sections = self.content.split("pkgname = ")
        ds_section = None
        for s in sections:
            if s.startswith("datastore\n") and not s.startswith("datastore-"):
                ds_section = s
                break
        assert ds_section is not None
        assert "\tbackup = etc/datastore/datastore.conf" in ds_section

    def test_global_section_no_depends(self):
        """Global (pkgbase) section should NOT have depends since they're per-package."""
        pkgbase_section = self.content.split("pkgname = ")[0]
        assert "\tdepends = " not in pkgbase_section

    def test_global_section_has_makedepends(self):
        pkgbase_section = self.content.split("pkgname = ")[0]
        assert "\tmakedepends = cmake" in pkgbase_section
        assert "\tmakedepends = openssl" in pkgbase_section


# ─── webproxy .SRCINFO (multi-arch) ───


class TestSrcinfoWebproxy:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_srcinfo("webproxy")

    def test_multi_arch(self):
        assert has_field(self.content, "arch", "x86_64")
        assert has_field(self.content, "arch", "aarch64")

    def test_four_sources(self):
        lines = srcinfo_lines(self.content)
        src_lines = [l for l in lines if "\tsource = " in l]
        assert len(src_lines) == 4

    def test_three_checksums(self):
        """Checksum count mismatch: 4 sources but only 3 sha256sums."""
        lines = srcinfo_lines(self.content)
        sha_lines = [l for l in lines if "\tsha256sums = " in l]
        assert len(sha_lines) == 3

    def test_optdepends(self):
        assert has_field(
            self.content, "optdepends",
            "geoip-database: for geo-location features"
        )


# ─── appserver .SRCINFO (epoch + nested variable expansion) ───


class TestSrcinfoAppserver:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_srcinfo("appserver")

    def test_epoch(self):
        assert has_field(self.content, "epoch", "2")

    def test_nested_variable_expansion_source(self):
        """Source URL uses _repobase (which uses _orgname) and _pkgsuffix."""
        assert has_field(
            self.content, "source",
            "https://releases.examplecorp.com/packages/appserver-stable-1.2.0.tar.gz"
        )

    def test_variable_expansion_url(self):
        """url field uses _orgname variable."""
        assert has_field(
            self.content, "url",
            "https://www.examplecorp.com/appserver"
        )

    def test_install_field(self):
        assert has_field(self.content, "install", "appserver.install")

    def test_versioned_depends(self):
        assert has_field(self.content, "depends", "jre-openjdk>=17")
        assert has_field(self.content, "depends", "netutils>=3.0")

    def test_versioned_makedepends(self):
        assert has_field(self.content, "makedepends", "jdk-openjdk>=17")
        assert has_field(self.content, "makedepends", "maven")

    def test_source_count(self):
        lines = srcinfo_lines(self.content)
        src_lines = [l for l in lines if "\tsource = " in l]
        assert len(src_lines) == 3


# ─── logcollector + loganalyzer .SRCINFO ───


class TestSrcinfoLogPackages:
    def test_logcollector_depends_on_loganalyzer(self):
        content = read_srcinfo("logcollector")
        assert has_field(content, "depends", "loganalyzer")

    def test_loganalyzer_depends_on_logcollector(self):
        content = read_srcinfo("loganalyzer")
        assert has_field(content, "depends", "logcollector")


# ─── .SRCINFO structural correctness ───


class TestSrcinfoStructure:
    @pytest.mark.parametrize("pkg_dir", PKG_DIRS)
    def test_tab_indentation(self, pkg_dir):
        """All field lines must be tab-indented."""
        content = read_srcinfo(pkg_dir)
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("pkgbase = ") or stripped.startswith("pkgname = "):
                assert not line.startswith("\t"), \
                    f"Section header should not be indented: {line}"
            elif " = " in stripped:
                assert line.startswith("\t"), \
                    f"Field line should be tab-indented: {line}"


# ─── dependency_graph.json ───


class TestDependencyGraph:
    @pytest.fixture(autouse=True)
    def setup(self):
        path = os.path.join(RESULTS_DIR, "dependency_graph.json")
        assert os.path.isfile(path), "dependency_graph.json not found"
        with open(path) as f:
            self.graph = json.load(f)

    def test_all_packages_present(self):
        for pkg in ALL_PKGNAMES:
            assert pkg in self.graph, f"Package {pkg} missing from graph"

    def test_datastore_depends_on_libs(self):
        assert "datastore-libs" in self.graph["datastore"]

    def test_datastore_client_depends_on_libs(self):
        assert "datastore-libs" in self.graph["datastore-client"]

    def test_logcollector_depends_on_loganalyzer(self):
        assert "loganalyzer" in self.graph["logcollector"]

    def test_loganalyzer_depends_on_logcollector(self):
        assert "logcollector" in self.graph["loganalyzer"]

    def test_appserver_depends_on_netutils(self):
        assert "netutils" in self.graph["appserver"]

    def test_netutils_no_internal_deps(self):
        assert self.graph["netutils"] == []

    def test_webproxy_no_internal_deps(self):
        assert self.graph["webproxy"] == []

    def test_datastore_libs_no_internal_deps(self):
        assert self.graph["datastore-libs"] == []


# ─── issues.json ───


class TestIssues:
    @pytest.fixture(autouse=True)
    def setup(self):
        path = os.path.join(RESULTS_DIR, "issues.json")
        assert os.path.isfile(path), "issues.json not found"
        with open(path) as f:
            self.issues = json.load(f)
        assert isinstance(self.issues, list)

    def test_checksum_mismatch_detected(self):
        """webproxy has 4 sources but 3 sha256sums."""
        matches = [
            i for i in self.issues
            if i.get("type") == "checksum_mismatch"
            and i.get("package") == "webproxy"
        ]
        assert len(matches) >= 1, "checksum_mismatch issue for webproxy not found"

    def test_circular_dependency_detected(self):
        """logcollector <-> loganalyzer form a cycle."""
        matches = [
            i for i in self.issues
            if i.get("type") == "circular_dependency"
            and i.get("package") in ("logcollector", "loganalyzer")
        ]
        assert len(matches) >= 1, "circular_dependency issue not found"

    def test_version_conflict_detected(self):
        """appserver requires netutils>=3.0 but repo provides 2.4.1."""
        matches = [
            i for i in self.issues
            if i.get("type") == "version_conflict"
            and i.get("package") == "appserver"
        ]
        assert len(matches) >= 1, "version_conflict issue for appserver not found"

    def test_no_false_positive_checksum(self):
        """Only webproxy should have a checksum mismatch."""
        wrong = [
            i for i in self.issues
            if i.get("type") == "checksum_mismatch"
            and i.get("package") != "webproxy"
        ]
        assert len(wrong) == 0, f"False positive checksum_mismatch: {wrong}"


# ─── install_order.json ───


class TestInstallOrder:
    @pytest.fixture(autouse=True)
    def setup(self):
        path = os.path.join(RESULTS_DIR, "install_order.json")
        assert os.path.isfile(path), "install_order.json not found"
        with open(path) as f:
            self.order = json.load(f)
        assert isinstance(self.order, list)

    def test_excludes_circular_deps(self):
        """Packages in cycles must not appear in install order."""
        assert "logcollector" not in self.order
        assert "loganalyzer" not in self.order

    def test_includes_non_circular(self):
        """Non-cycle packages must appear."""
        expected = {"netutils", "webproxy", "datastore-libs",
                    "datastore", "datastore-client", "appserver"}
        assert expected.issubset(set(self.order)), \
            f"Missing packages: {expected - set(self.order)}"

    def test_datastore_libs_before_datastore(self):
        idx_libs = self.order.index("datastore-libs")
        idx_ds = self.order.index("datastore")
        assert idx_libs < idx_ds, "datastore-libs must come before datastore"

    def test_datastore_libs_before_client(self):
        idx_libs = self.order.index("datastore-libs")
        idx_client = self.order.index("datastore-client")
        assert idx_libs < idx_client, "datastore-libs must come before datastore-client"

    def test_netutils_before_appserver(self):
        idx_nu = self.order.index("netutils")
        idx_as = self.order.index("appserver")
        assert idx_nu < idx_as, "netutils must come before appserver"

    def test_no_duplicates(self):
        assert len(self.order) == len(set(self.order)), "Duplicates in install order"
