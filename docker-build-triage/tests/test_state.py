
import json
import os
import re
import subprocess

BUILDS_DIR = "/app/builds"
REPORT_PATH = "/app/report.json"
TRIAGE_SCRIPT = "/app/triage.py"

BUILD_NAMES = [
    "python-cffi",
    "go-pcap",
    "rust-openssl",
    "cpp-boost",
    "node-sharp",
    "ruby-nokogiri",
    "php-zip",
    "java-spring",
]


# ── Helper ──────────────────────────────────────────────────────────────────

def read_dockerfile(build_name):
    path = os.path.join(BUILDS_DIR, build_name, "Dockerfile.fixed")
    assert os.path.isfile(path), f"Dockerfile.fixed missing for {build_name}"
    with open(path) as f:
        return f.read()


def dockerfile_has(content, *patterns):
    """Check that every pattern appears somewhere in the Dockerfile content (case-insensitive)."""
    lower = content.lower()
    for p in patterns:
        assert p.lower() in lower, f"Dockerfile.fixed missing expected content: {p!r}"


def dockerfile_has_any(content, *patterns):
    """Check that at least one pattern appears in the Dockerfile content (case-insensitive)."""
    lower = content.lower()
    for p in patterns:
        if p.lower() in lower:
            return
    assert False, f"Dockerfile.fixed missing any of: {patterns!r}"


def dockerfile_not_has(content, *patterns):
    """Check that none of the patterns appear in the Dockerfile (case-insensitive)."""
    lower = content.lower()
    for p in patterns:
        assert p.lower() not in lower, f"Dockerfile.fixed should NOT contain: {p!r}"


# ── Dockerfile.fixed existence ──────────────────────────────────────────────

class TestDockerfilesExist:
    def test_all_dockerfile_fixed_exist(self):
        for name in BUILD_NAMES:
            path = os.path.join(BUILDS_DIR, name, "Dockerfile.fixed")
            assert os.path.isfile(path), f"Missing Dockerfile.fixed for {name}"


# ── Python-cffi fixes ──────────────────────────────────────────────────────

class TestPythonCffi:
    def test_has_libffi_dev(self):
        content = read_dockerfile("python-cffi")
        dockerfile_has(content, "libffi-dev")

    def test_libffi_before_pip(self):
        content = read_dockerfile("python-cffi")
        # The apt-get install of libffi-dev must appear before pip install
        apt_pos = content.lower().find("libffi-dev")
        pip_pos = content.lower().find("pip install")
        assert apt_pos < pip_pos, "libffi-dev must be installed before pip install"

    def test_valid_base_image(self):
        content = read_dockerfile("python-cffi")
        # Base image should still be python 3.11
        dockerfile_has_any(content, "from python:3.11", "from python:3.12", "from python:3")


# ── Go-pcap fixes ──────────────────────────────────────────────────────────

class TestGoPcap:
    def test_cgo_enabled(self):
        content = read_dockerfile("go-pcap")
        # Must not have CGO_ENABLED=0; should have CGO_ENABLED=1 or no override
        if "cgo_enabled" in content.lower():
            dockerfile_not_has(content, "CGO_ENABLED=0")
            dockerfile_has(content, "CGO_ENABLED=1")

    def test_has_pcap_dev(self):
        content = read_dockerfile("go-pcap")
        dockerfile_has(content, "libpcap-dev")

    def test_has_compiler(self):
        content = read_dockerfile("go-pcap")
        # Needs gcc (or build-base on alpine, or build-essential)
        dockerfile_has_any(content, "gcc", "build-base", "build-essential")

    def test_not_alpine_or_has_apk(self):
        content = read_dockerfile("go-pcap")
        lower = content.lower()
        # If alpine base, must use apk not apt-get. If debian-based, apt-get is fine.
        if "alpine" in lower:
            dockerfile_has_any(content, "apk add", "apk install")
        else:
            dockerfile_has_any(content, "apt-get", "apt ")


# ── Rust-openssl fixes ─────────────────────────────────────────────────────

class TestRustOpenssl:
    def test_has_libssl_dev(self):
        content = read_dockerfile("rust-openssl")
        dockerfile_has(content, "libssl-dev")

    def test_has_pkg_config(self):
        content = read_dockerfile("rust-openssl")
        dockerfile_has(content, "pkg-config")

    def test_dev_not_runtime_only(self):
        content = read_dockerfile("rust-openssl")
        # Must have libssl-dev, not just openssl alone
        dockerfile_has(content, "libssl-dev")


# ── C++ Boost fixes ────────────────────────────────────────────────────────

class TestCppBoost:
    def test_not_ubuntu_1804(self):
        content = read_dockerfile("cpp-boost")
        dockerfile_not_has(content, "ubuntu:18.04")

    def test_has_newer_ubuntu(self):
        content = read_dockerfile("cpp-boost")
        dockerfile_has_any(
            content,
            "ubuntu:22.04", "ubuntu:24.04", "ubuntu:23",
            "ubuntu:noble", "ubuntu:jammy",
            "gcc:", "debian:",
        )

    def test_has_cmake(self):
        content = read_dockerfile("cpp-boost")
        dockerfile_has(content, "cmake")

    def test_has_boost(self):
        content = read_dockerfile("cpp-boost")
        dockerfile_has_any(content, "libboost-all-dev", "libboost-dev", "libboost")


# ── Node.js sharp fixes ───────────────────────────────────────────────────

class TestNodeSharp:
    def test_has_libvips(self):
        content = read_dockerfile("node-sharp")
        dockerfile_has(content, "libvips-dev")

    def test_has_pkg_config(self):
        content = read_dockerfile("node-sharp")
        dockerfile_has_any(content, "pkg-config", "build-essential")

    def test_system_deps_before_npm(self):
        content = read_dockerfile("node-sharp")
        vips_pos = content.lower().find("libvips-dev")
        npm_pos = content.lower().find("npm")
        assert vips_pos < npm_pos, "libvips-dev must be installed before npm install"


# ── Ruby nokogiri fixes ───────────────────────────────────────────────────

class TestRubyNokogiri:
    def test_has_libxml2_dev(self):
        content = read_dockerfile("ruby-nokogiri")
        dockerfile_has(content, "libxml2-dev")

    def test_has_libxslt_dev(self):
        content = read_dockerfile("ruby-nokogiri")
        dockerfile_has_any(content, "libxslt1-dev", "libxslt-dev")


# ── PHP zip fixes ──────────────────────────────────────────────────────────

class TestPhpZip:
    def test_has_docker_php_ext_install(self):
        content = read_dockerfile("php-zip")
        # This is the KEY insight: libzip-dev alone is insufficient;
        # must also compile the PHP extension
        dockerfile_has(content, "docker-php-ext-install")

    def test_installs_zip_extension(self):
        content = read_dockerfile("php-zip")
        # docker-php-ext-install zip
        assert re.search(
            r"docker-php-ext-install\s+.*\bzip\b", content, re.IGNORECASE
        ), "Must run docker-php-ext-install zip"

    def test_keeps_libzip_dev(self):
        content = read_dockerfile("php-zip")
        dockerfile_has(content, "libzip-dev")


# ── Java Spring fixes ─────────────────────────────────────────────────────

class TestJavaSpring:
    def test_not_jdk11(self):
        content = read_dockerfile("java-spring")
        dockerfile_not_has(content, "openjdk:11", "jdk-11", "java-11")

    def test_jdk_17_or_higher(self):
        content = read_dockerfile("java-spring")
        dockerfile_has_any(
            content,
            "openjdk:17", "openjdk:21", "eclipse-temurin:17", "eclipse-temurin:21",
            "amazoncorretto:17", "amazoncorretto:21",
            "jdk:17", "jdk:21", "jdk-17", "jdk-21",
            "maven:3", "gradle:",
        )

    def test_uses_build_tool(self):
        content = read_dockerfile("java-spring")
        # Should use Maven or Gradle, not raw javac
        dockerfile_has_any(content, "mvn", "maven", "gradle", "gradlew")


# ── report.json structure and content ──────────────────────────────────────

class TestReportStructure:
    def _load_report(self):
        assert os.path.isfile(REPORT_PATH), "report.json does not exist"
        with open(REPORT_PATH) as f:
            return json.load(f)

    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH)

    def test_has_builds_key(self):
        report = self._load_report()
        assert "builds" in report, "report.json must have 'builds' key"

    def test_has_summary_key(self):
        report = self._load_report()
        assert "summary" in report, "report.json must have 'summary' key"

    def test_all_builds_present(self):
        report = self._load_report()
        for name in BUILD_NAMES:
            assert name in report["builds"], f"Build {name} missing from report"

    def test_builds_have_required_fields(self):
        report = self._load_report()
        required = [
            "failure_categories", "root_cause", "fixes",
            "system_packages_added", "base_image_change", "env_changes",
        ]
        for name in BUILD_NAMES:
            entry = report["builds"][name]
            for field in required:
                assert field in entry, f"Build {name} missing field '{field}'"

    def test_summary_total_builds(self):
        report = self._load_report()
        assert report["summary"]["total_builds"] == 8

    def test_summary_has_failure_distribution(self):
        report = self._load_report()
        dist = report["summary"]["failure_distribution"]
        assert isinstance(dist, dict)
        assert len(dist) > 0


class TestReportCategories:
    VALID_CATEGORIES = {
        "missing_system_dep", "version_conflict", "build_tool_missing",
        "incorrect_base_image", "env_misconfiguration", "missing_build_flag",
        "package_conflict", "test_framework_missing",
    }

    def _load_report(self):
        with open(REPORT_PATH) as f:
            return json.load(f)

    def test_categories_are_valid(self):
        report = self._load_report()
        for name, entry in report["builds"].items():
            for cat in entry["failure_categories"]:
                assert cat in self.VALID_CATEGORIES, (
                    f"Build {name}: invalid category '{cat}'"
                )

    def test_python_cffi_category(self):
        report = self._load_report()
        cats = report["builds"]["python-cffi"]["failure_categories"]
        assert "missing_system_dep" in cats

    def test_go_pcap_categories(self):
        report = self._load_report()
        cats = report["builds"]["go-pcap"]["failure_categories"]
        assert "missing_system_dep" in cats or "env_misconfiguration" in cats

    def test_rust_openssl_category(self):
        report = self._load_report()
        cats = report["builds"]["rust-openssl"]["failure_categories"]
        assert "missing_system_dep" in cats

    def test_cpp_boost_categories(self):
        report = self._load_report()
        cats = report["builds"]["cpp-boost"]["failure_categories"]
        has_image = "incorrect_base_image" in cats
        has_tool = "build_tool_missing" in cats
        assert has_image or has_tool, (
            "cpp-boost must have incorrect_base_image or build_tool_missing"
        )

    def test_node_sharp_category(self):
        report = self._load_report()
        cats = report["builds"]["node-sharp"]["failure_categories"]
        assert "missing_system_dep" in cats

    def test_ruby_nokogiri_category(self):
        report = self._load_report()
        cats = report["builds"]["ruby-nokogiri"]["failure_categories"]
        assert "missing_system_dep" in cats

    def test_php_zip_category(self):
        report = self._load_report()
        cats = report["builds"]["php-zip"]["failure_categories"]
        assert "env_misconfiguration" in cats or "missing_system_dep" in cats

    def test_java_spring_categories(self):
        report = self._load_report()
        cats = report["builds"]["java-spring"]["failure_categories"]
        has_image = "incorrect_base_image" in cats
        has_tool = "build_tool_missing" in cats
        assert has_image or has_tool, (
            "java-spring must have incorrect_base_image or build_tool_missing"
        )


class TestReportPackages:
    def _load_report(self):
        with open(REPORT_PATH) as f:
            return json.load(f)

    def test_python_cffi_packages(self):
        report = self._load_report()
        pkgs = [p.lower() for p in report["builds"]["python-cffi"]["system_packages_added"]]
        assert "libffi-dev" in pkgs

    def test_rust_openssl_packages(self):
        report = self._load_report()
        pkgs = [p.lower() for p in report["builds"]["rust-openssl"]["system_packages_added"]]
        assert "libssl-dev" in pkgs
        assert "pkg-config" in pkgs

    def test_node_sharp_packages(self):
        report = self._load_report()
        pkgs = [p.lower() for p in report["builds"]["node-sharp"]["system_packages_added"]]
        assert "libvips-dev" in pkgs

    def test_ruby_nokogiri_packages(self):
        report = self._load_report()
        pkgs = [p.lower() for p in report["builds"]["ruby-nokogiri"]["system_packages_added"]]
        assert "libxml2-dev" in pkgs
        has_xslt = "libxslt1-dev" in pkgs or "libxslt-dev" in pkgs
        assert has_xslt

    def test_go_pcap_packages(self):
        report = self._load_report()
        pkgs = [p.lower() for p in report["builds"]["go-pcap"]["system_packages_added"]]
        assert "libpcap-dev" in pkgs


# ── triage.py re-runnability ───────────────────────────────────────────────

class TestTriageScript:
    def test_triage_script_exists(self):
        assert os.path.isfile(TRIAGE_SCRIPT), "triage.py does not exist"

    def test_triage_script_runs(self):
        # Remove existing outputs, then re-run
        for name in BUILD_NAMES:
            fixed = os.path.join(BUILDS_DIR, name, "Dockerfile.fixed")
            if os.path.exists(fixed):
                os.rename(fixed, fixed + ".bak")
        if os.path.exists(REPORT_PATH):
            os.rename(REPORT_PATH, REPORT_PATH + ".bak")

        result = subprocess.run(
            ["python3", TRIAGE_SCRIPT],
            capture_output=True, text=True, timeout=120, cwd="/app"
        )

        # Restore backups if re-run failed
        if result.returncode != 0:
            for name in BUILD_NAMES:
                bak = os.path.join(BUILDS_DIR, name, "Dockerfile.fixed.bak")
                fixed = os.path.join(BUILDS_DIR, name, "Dockerfile.fixed")
                if os.path.exists(bak):
                    os.rename(bak, fixed)
            if os.path.exists(REPORT_PATH + ".bak"):
                os.rename(REPORT_PATH + ".bak", REPORT_PATH)

        assert result.returncode == 0, (
            f"triage.py failed with exit code {result.returncode}\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )

        # Verify re-run produced outputs
        assert os.path.isfile(REPORT_PATH), "triage.py did not regenerate report.json"
        for name in BUILD_NAMES:
            fixed = os.path.join(BUILDS_DIR, name, "Dockerfile.fixed")
            assert os.path.isfile(fixed), (
                f"triage.py did not regenerate Dockerfile.fixed for {name}"
            )

        # Clean up backups
        for name in BUILD_NAMES:
            bak = os.path.join(BUILDS_DIR, name, "Dockerfile.fixed.bak")
            if os.path.exists(bak):
                os.remove(bak)
        if os.path.exists(REPORT_PATH + ".bak"):
            os.remove(REPORT_PATH + ".bak")

    def test_rerun_report_valid(self):
        """After re-running triage.py, report should still be valid JSON with correct structure."""
        assert os.path.isfile(REPORT_PATH)
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert "builds" in report
        assert "summary" in report
        assert len(report["builds"]) == 8
