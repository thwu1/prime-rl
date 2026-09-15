"""
Verification tests for the netdaemon project v3.0.0 release.
Tests that build, install, packaging, symbol visibility, and cmake config are correct.
"""

import subprocess
import os
import re
import shutil
import pytest

APP_DIR = "/app"
BUILD_DIR = "/app/build"
INSTALL_DIR = "/tmp/nd_install"
INSTALL_PREFIX = os.path.join(INSTALL_DIR, "usr", "local")


@pytest.fixture(scope="session")
def build_results():
    """Configure, build, and install the project once for all tests."""
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    if os.path.exists(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR)

    os.makedirs(BUILD_DIR, exist_ok=True)
    os.makedirs(INSTALL_DIR, exist_ok=True)

    results = {}

    # Configure
    r = subprocess.run(
        ["cmake", "..", f"-DCMAKE_INSTALL_PREFIX={INSTALL_PREFIX}"],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=120
    )
    results["cmake_rc"] = r.returncode
    results["cmake_stderr"] = r.stderr
    results["cmake_stdout"] = r.stdout

    if r.returncode != 0:
        results["build_rc"] = -1
        results["build_stderr"] = "skipped: cmake failed"
        results["install_rc"] = -1
        results["install_stderr"] = "skipped: cmake failed"
        return results

    # Build
    r = subprocess.run(
        ["cmake", "--build", ".", "--", "-j4"],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=300
    )
    results["build_rc"] = r.returncode
    results["build_stderr"] = r.stderr

    if r.returncode != 0:
        results["install_rc"] = -1
        results["install_stderr"] = "skipped: build failed"
        return results

    # Install
    r = subprocess.run(
        ["cmake", "--install", "."],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=60
    )
    results["install_rc"] = r.returncode
    results["install_stderr"] = r.stderr

    return results


# ---------------------------------------------------------------------------
# Build system tests
# ---------------------------------------------------------------------------

def test_cmake_configures(build_results):
    """CMake configuration must succeed."""
    assert build_results["cmake_rc"] == 0, \
        f"cmake configuration failed:\n{build_results['cmake_stderr']}"


def test_project_builds(build_results):
    """Project must compile and link without errors."""
    assert build_results["build_rc"] == 0, \
        f"Build failed:\n{build_results['build_stderr']}"


def test_install_succeeds(build_results):
    """cmake --install must succeed."""
    assert build_results["install_rc"] == 0, \
        f"Install failed:\n{build_results['install_stderr']}"


# ---------------------------------------------------------------------------
# Binary tests
# ---------------------------------------------------------------------------

def _find_in_build(name):
    """Find a file by name under the build directory."""
    for root, dirs, files in os.walk(BUILD_DIR):
        if name in files:
            return os.path.join(root, name)
    return None


def test_ndcli_exists(build_results):
    """ndcli binary must exist after build."""
    if build_results["build_rc"] != 0:
        pytest.skip("Build failed")
    assert _find_in_build("ndcli") is not None, "ndcli binary not found"


def test_ndserver_exists(build_results):
    """ndserver binary must exist after build."""
    if build_results["build_rc"] != 0:
        pytest.skip("Build failed")
    assert _find_in_build("ndserver") is not None, "ndserver binary not found"


def test_ndcli_runs(build_results):
    """ndcli must execute and report version 3.0.0."""
    if build_results["build_rc"] != 0:
        pytest.skip("Build failed")
    ndcli = _find_in_build("ndcli")
    assert ndcli is not None
    r = subprocess.run([ndcli], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"ndcli crashed: {r.stderr}"
    assert "3.0.0" in r.stdout, f"ndcli should report v3.0.0, got: {r.stdout}"


def test_ndserver_runs(build_results):
    """ndserver must execute and report version 3.0.0."""
    if build_results["build_rc"] != 0:
        pytest.skip("Build failed")
    ndserver = _find_in_build("ndserver")
    assert ndserver is not None
    r = subprocess.run([ndserver], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"ndserver crashed: {r.stderr}"
    assert "3.0.0" in r.stdout, f"ndserver should report v3.0.0, got: {r.stdout}"


# ---------------------------------------------------------------------------
# Library versioning tests
# ---------------------------------------------------------------------------

def test_libndcore_soversion(build_results):
    """libndcore SONAME must be libndcore.so.3 (SOVERSION = major version)."""
    if build_results["build_rc"] != 0:
        pytest.skip("Build failed")
    libndcore = _find_in_build("libndcore.so")
    assert libndcore is not None, "libndcore.so not found in build"
    r = subprocess.run(
        ["readelf", "-d", libndcore], capture_output=True, text=True
    )
    assert r.returncode == 0, f"readelf failed: {r.stderr}"
    assert "libndcore.so.3" in r.stdout, \
        f"SONAME should be libndcore.so.3:\n{r.stdout}"


# ---------------------------------------------------------------------------
# Install path tests
# ---------------------------------------------------------------------------

def test_library_in_lib_dir(build_results):
    """Libraries must install to <prefix>/lib/."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    lib_dir = os.path.join(INSTALL_PREFIX, "lib")
    assert os.path.isdir(lib_dir), f"lib dir missing: {lib_dir}"
    libs = os.listdir(lib_dir)
    assert any("libndcore" in f for f in libs), \
        f"libndcore not found in {lib_dir}, contents: {libs}"
    assert any("libndcrypto" in f for f in libs), \
        f"libndcrypto not found in {lib_dir}, contents: {libs}"


def test_headers_in_include_dir(build_results):
    """Headers must install to <prefix>/include/netdaemon/."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    inc_dir = os.path.join(INSTALL_PREFIX, "include", "netdaemon")
    assert os.path.isdir(inc_dir), f"include dir missing: {inc_dir}"
    assert os.path.isfile(os.path.join(inc_dir, "ndcore.h")), \
        "ndcore.h not installed"
    assert os.path.isfile(os.path.join(inc_dir, "ndcrypto.h")), \
        "ndcrypto.h not installed"


def test_binaries_in_bin_dir(build_results):
    """Binaries must install to <prefix>/bin/."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    bin_dir = os.path.join(INSTALL_PREFIX, "bin")
    assert os.path.isfile(os.path.join(bin_dir, "ndcli")), \
        "ndcli not installed to bin/"
    assert os.path.isfile(os.path.join(bin_dir, "ndserver")), \
        "ndserver not installed to bin/"


def test_pkgconfig_in_lib_pkgconfig(build_results):
    """pkg-config .pc file must install to <prefix>/lib/pkgconfig/."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    pc_dir = os.path.join(INSTALL_PREFIX, "lib", "pkgconfig")
    assert os.path.isdir(pc_dir), f"pkgconfig dir missing: {pc_dir}"
    pc_files = [f for f in os.listdir(pc_dir) if f.endswith(".pc")]
    assert len(pc_files) > 0, "No .pc files installed"


# ---------------------------------------------------------------------------
# pkg-config content tests
# ---------------------------------------------------------------------------

def _find_pc_file():
    """Find the installed .pc file."""
    for root, dirs, files in os.walk(INSTALL_DIR):
        for f in files:
            if f.endswith(".pc"):
                return os.path.join(root, f)
    return None


def test_pkgconfig_version(build_results):
    """pkg-config file must report Version: 3.0.0."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    pc = _find_pc_file()
    assert pc is not None, "No .pc file found"
    with open(pc) as fh:
        content = fh.read()
    assert "Version: 3.0.0" in content, \
        f"pkg-config version should be 3.0.0:\n{content}"


def test_pkgconfig_libs(build_results):
    """pkg-config Libs must reference -lndcore (not -lnetdaemon)."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    pc = _find_pc_file()
    assert pc is not None
    with open(pc) as fh:
        content = fh.read()
    assert "-lndcore" in content, \
        f"pkg-config Libs should reference -lndcore:\n{content}"
    assert "-lnetdaemon" not in content, \
        f"pkg-config Libs should NOT reference -lnetdaemon:\n{content}"


# ---------------------------------------------------------------------------
# Systemd unit file tests
# ---------------------------------------------------------------------------

def _read_service():
    return open(os.path.join(APP_DIR, "pkg", "netdaemon.service")).read()


def test_systemd_no_daemonize():
    """Systemd unit must not use --daemonize."""
    content = _read_service()
    assert "--daemonize" not in content, \
        "--daemonize flag should not be present"


def test_systemd_correct_binary():
    """Systemd ExecStart must reference ndserver."""
    content = _read_service()
    assert "ndserver" in content, \
        "ExecStart should reference ndserver"


def test_systemd_correct_type():
    """Systemd Type must not be forking."""
    content = _read_service()
    assert "Type=forking" not in content, \
        "Type should not be forking"
    assert re.search(r'Type\s*=\s*(simple|exec|notify)', content), \
        "Type should be simple, exec, or notify"


# ---------------------------------------------------------------------------
# Package manifest tests
# ---------------------------------------------------------------------------

def test_no_manifest_conflicts():
    """No file should appear in multiple package manifests."""
    manifest_dir = os.path.join(APP_DIR, "pkg", "manifests")
    all_files = {}
    conflicts = []

    for manifest_name in sorted(os.listdir(manifest_dir)):
        manifest_path = os.path.join(manifest_dir, manifest_name)
        with open(manifest_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line in all_files:
                    conflicts.append(
                        f"'{line}' in both {all_files[line]} and "
                        f"{manifest_name}"
                    )
                else:
                    all_files[line] = manifest_name

    assert len(conflicts) == 0, \
        "File conflicts between packages:\n" + "\n".join(conflicts)


# ---------------------------------------------------------------------------
# CMake config-mode package tests
# ---------------------------------------------------------------------------

def test_cmake_config_installed(build_results):
    """A netdaemonConfig.cmake file must be installed."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    cmake_dir = os.path.join(INSTALL_PREFIX, "lib", "cmake", "netdaemon")
    assert os.path.isdir(cmake_dir), \
        f"cmake config directory not found at {cmake_dir}"
    config_file = os.path.join(cmake_dir, "netdaemonConfig.cmake")
    assert os.path.isfile(config_file), \
        "netdaemonConfig.cmake not installed"


def test_cmake_config_version_installed(build_results):
    """A netdaemonConfigVersion.cmake must be installed."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    cmake_dir = os.path.join(INSTALL_PREFIX, "lib", "cmake", "netdaemon")
    version_file = os.path.join(cmake_dir, "netdaemonConfigVersion.cmake")
    assert os.path.isfile(version_file), \
        "netdaemonConfigVersion.cmake not installed"


def test_cmake_exports_namespaced_targets(build_results):
    """Exported cmake targets must include netdaemon::ndcore and netdaemon::ndcrypto."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    cmake_dir = os.path.join(INSTALL_PREFIX, "lib", "cmake", "netdaemon")
    if not os.path.isdir(cmake_dir):
        pytest.fail("cmake config directory not found")

    all_content = ""
    for f in os.listdir(cmake_dir):
        fpath = os.path.join(cmake_dir, f)
        if os.path.isfile(fpath):
            with open(fpath) as fh:
                all_content += fh.read()

    assert "netdaemon::ndcore" in all_content, \
        "Target netdaemon::ndcore not found in cmake config files"
    assert "netdaemon::ndcrypto" in all_content, \
        "Target netdaemon::ndcrypto not found in cmake config files"


def test_find_package_consumer_builds(build_results):
    """A downstream project using find_package(netdaemon) must configure and build."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")

    consumer_dir = "/tmp/nd_consumer_test"
    if os.path.exists(consumer_dir):
        shutil.rmtree(consumer_dir)
    os.makedirs(os.path.join(consumer_dir, "build"))

    with open(os.path.join(consumer_dir, "CMakeLists.txt"), "w") as f:
        f.write(
            'cmake_minimum_required(VERSION 3.14)\n'
            'project(consumer C)\n'
            'find_package(netdaemon REQUIRED)\n'
            'add_executable(consumer consumer.c)\n'
            'target_link_libraries(consumer PRIVATE netdaemon::ndcrypto)\n'
        )

    with open(os.path.join(consumer_dir, "consumer.c"), "w") as f:
        f.write(
            '#include "ndcore.h"\n'
            '#include "ndcrypto.h"\n'
            '#include <stdio.h>\n'
            'int main(void) {\n'
            '    printf("consumer: %s\\n", nd_version_string());\n'
            '    char hash[65];\n'
            '    nd_hash_password("test", hash, sizeof(hash));\n'
            '    printf("hash: %s\\n", hash);\n'
            '    return 0;\n'
            '}\n'
        )

    r = subprocess.run(
        ["cmake", "..", f"-DCMAKE_PREFIX_PATH={INSTALL_PREFIX}"],
        cwd=os.path.join(consumer_dir, "build"),
        capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, \
        f"Consumer cmake configure failed:\n{r.stderr}\n{r.stdout}"

    r = subprocess.run(
        ["cmake", "--build", "."],
        cwd=os.path.join(consumer_dir, "build"),
        capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, \
        f"Consumer build failed:\n{r.stderr}"

    env = os.environ.copy()
    lib_dir = os.path.join(INSTALL_PREFIX, "lib")
    env["LD_LIBRARY_PATH"] = lib_dir + ":" + env.get("LD_LIBRARY_PATH", "")
    consumer_bin = os.path.join(consumer_dir, "build", "consumer")
    r = subprocess.run(
        [consumer_bin], capture_output=True, text=True, timeout=10, env=env
    )
    assert r.returncode == 0, f"Consumer binary crashed: {r.stderr}"
    assert "3.0.0" in r.stdout, \
        f"Consumer should report version 3.0.0, got: {r.stdout}"


# ---------------------------------------------------------------------------
# Symbol visibility tests (version scripts)
# ---------------------------------------------------------------------------

def _get_dynamic_functions(lib_path):
    """Get exported function symbols from a shared library, stripping version tags."""
    r = subprocess.run(
        ["nm", "-D", "--defined-only", lib_path],
        capture_output=True, text=True
    )
    assert r.returncode == 0, f"nm failed on {lib_path}: {r.stderr}"
    symbols = set()
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        sym_type = parts[1]
        sym_name = parts[2]
        if sym_type not in ("T", "W"):
            continue
        if "@@" in sym_name:
            sym_name = sym_name.split("@@")[0]
        elif "@" in sym_name:
            sym_name = sym_name.split("@")[0]
        if sym_name.startswith("_"):
            continue
        symbols.add(sym_name)
    return symbols


def test_ndcore_exports_only_public_api(build_results):
    """libndcore must export only its public API symbols; internal helpers must be hidden."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    lib_dir = os.path.join(INSTALL_PREFIX, "lib")
    lib_path = os.path.join(lib_dir, "libndcore.so")
    assert os.path.exists(lib_path), f"libndcore.so not found at {lib_path}"

    exported = _get_dynamic_functions(lib_path)

    public_api = {
        "nd_config_init", "nd_config_free", "nd_config_load",
        "nd_log", "nd_version_string"
    }
    for sym in public_api:
        assert sym in exported, \
            f"Public API symbol '{sym}' must be exported from libndcore"

    internal_symbols = {"parse_config_value", "reset_config_defaults"}
    for sym in internal_symbols:
        assert sym not in exported, \
            f"Internal symbol '{sym}' must NOT be exported from libndcore"

    unexpected = exported - public_api
    assert len(unexpected) == 0, \
        f"Unexpected symbols exported from libndcore: {unexpected}"


def test_ndcrypto_exports_only_public_api(build_results):
    """libndcrypto must export only its public API symbols; internal helpers must be hidden."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    lib_dir = os.path.join(INSTALL_PREFIX, "lib")
    lib_path = os.path.join(lib_dir, "libndcrypto.so")
    assert os.path.exists(lib_path), f"libndcrypto.so not found at {lib_path}"

    exported = _get_dynamic_functions(lib_path)

    public_api = {
        "nd_hash_password", "nd_verify_password", "nd_generate_token"
    }
    for sym in public_api:
        assert sym in exported, \
            f"Public API symbol '{sym}' must be exported from libndcrypto"

    internal_symbols = {"compute_digest"}
    for sym in internal_symbols:
        assert sym not in exported, \
            f"Internal symbol '{sym}' must NOT be exported from libndcrypto"

    unexpected = exported - public_api
    assert len(unexpected) == 0, \
        f"Unexpected symbols exported from libndcrypto: {unexpected}"


def test_version_scripts_in_use(build_results):
    """Both libraries must use version scripts (dynamic symbols carry version tags)."""
    if build_results.get("install_rc", -1) != 0:
        pytest.skip("Install failed")
    lib_dir = os.path.join(INSTALL_PREFIX, "lib")
    for libname in ("libndcore", "libndcrypto"):
        lib_path = os.path.join(lib_dir, f"{libname}.so")
        assert os.path.exists(lib_path), f"{libname}.so not found"
        r = subprocess.run(
            ["nm", "-D", "--defined-only", lib_path],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"nm failed on {libname}: {r.stderr}"
        assert "@@" in r.stdout, \
            f"{libname}: no version tags found in dynamic symbols — " \
            f"a GNU ld version script must be used"
