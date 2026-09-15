"""Tests for the netmon FTBFS repair and ABI architecture task.

Verifies that all build bugs have been fixed, the library ABI is correct
(symbol visibility, SONAME, GNU version tags), and the project builds,
installs, and runs correctly with Debian hardening flags.
"""

import subprocess
import os
import re
import pytest

BUILD_DIR = "/app/build_verify"
INSTALL_DIR = "/tmp/verify_install"


def run_cmd(cmd, cwd=None, env=None):
    """Run a command and return the result."""
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env=env
    )


def find_lib_path():
    """Find the installed libnetmon.so (dev symlink)."""
    for p in [
        os.path.join(INSTALL_DIR, "usr/lib/libnetmon.so"),
        os.path.join(INSTALL_DIR, "usr/lib/x86_64-linux-gnu/libnetmon.so"),
    ]:
        if os.path.exists(p):
            return p
    return None


def find_lib_dir():
    """Find the directory containing the installed library."""
    for d in ["usr/lib", "usr/lib/x86_64-linux-gnu"]:
        full = os.path.join(INSTALL_DIR, d)
        if os.path.exists(os.path.join(full, "libnetmon.so")):
            return full
    return None


def find_versioned_lib():
    """Find the actual versioned .so file (not the symlink)."""
    for d in ["usr/lib", "usr/lib/x86_64-linux-gnu"]:
        full = os.path.join(INSTALL_DIR, d)
        candidate = os.path.join(full, "libnetmon.so.2.0.0")
        if os.path.exists(candidate):
            return candidate
    return find_lib_path()


class TestNetmonBuild:
    """Test that the netmon project builds and installs correctly."""

    @classmethod
    def setup_class(cls):
        """Build the project from scratch."""
        subprocess.run(["rm", "-rf", BUILD_DIR, INSTALL_DIR], check=False)
        os.makedirs(BUILD_DIR, exist_ok=True)

        cls.cmake_result = run_cmd(
            ["cmake", "/app",
             "-DCMAKE_INSTALL_PREFIX=/usr",
             "-DCMAKE_C_FLAGS=-Werror=implicit-function-declaration"],
            cwd=BUILD_DIR
        )

        cls.make_result = None
        if cls.cmake_result.returncode == 0:
            cls.make_result = run_cmd(
                ["make", "-j4", "VERBOSE=1"],
                cwd=BUILD_DIR
            )

        cls.install_result = None
        if cls.make_result and cls.make_result.returncode == 0:
            cls.install_result = run_cmd(
                ["make", "install", f"DESTDIR={INSTALL_DIR}"],
                cwd=BUILD_DIR
            )

    def _assert_built(self):
        assert self.install_result is not None and \
               self.install_result.returncode == 0, "Build/install failed"

    def test_cmake_succeeds(self):
        """CMake configuration must complete without errors."""
        assert self.cmake_result.returncode == 0, (
            f"cmake failed:\nSTDOUT:\n{self.cmake_result.stdout}\n"
            f"STDERR:\n{self.cmake_result.stderr}"
        )

    def test_make_succeeds(self):
        """Build must complete without errors."""
        assert self.make_result is not None, "make did not run (cmake failed)"
        assert self.make_result.returncode == 0, (
            f"make failed:\nSTDOUT:\n{self.make_result.stdout}\n"
            f"STDERR:\n{self.make_result.stderr}"
        )

    def test_install_succeeds(self):
        """Installation must complete without errors."""
        assert self.install_result is not None, "install did not run"
        assert self.install_result.returncode == 0, (
            f"make install failed:\nSTDOUT:\n{self.install_result.stdout}\n"
            f"STDERR:\n{self.install_result.stderr}"
        )

    def test_library_installed(self):
        """The shared library must be produced."""
        self._assert_built()
        assert find_lib_path() is not None, \
            "libnetmon.so not found in install tree"

    def test_headers_correct_path(self):
        """Headers must be installed under netmon-v2/."""
        self._assert_built()
        api_h = os.path.join(INSTALL_DIR, "usr/include/netmon-v2/api.h")
        assert os.path.exists(api_h), \
            f"api.h not found at expected path {api_h}"

    def test_generated_config_valid(self):
        """Generated config header must exist with version macros."""
        self._assert_built()
        config_h = os.path.join(
            INSTALL_DIR, "usr/include/netmon-v2/generated_config.h"
        )
        assert os.path.exists(config_h), \
            f"generated_config.h not found at {config_h}"

        with open(config_h, 'r') as f:
            content = f.read()

        assert "#define NETMON_VERSION_MAJOR" in content, \
            "Missing NETMON_VERSION_MAJOR in generated header"
        assert "#define NETMON_VERSION_STRING" in content, \
            "Missing NETMON_VERSION_STRING in generated header"
        assert "#define NETMON_BUILD_HASH" in content, \
            "Missing NETMON_BUILD_HASH in generated header"

    def test_soname_correct(self):
        """SONAME must follow Debian conventions: libnetmon.so.<major>."""
        self._assert_built()

        lib_path = find_versioned_lib()
        assert lib_path is not None, "libnetmon.so not found"

        result = run_cmd(["readelf", "-W", "-d", lib_path])
        assert result.returncode == 0, f"readelf failed: {result.stderr}"

        soname_match = re.search(r'SONAME.*\[([^\]]+)\]', result.stdout)
        assert soname_match is not None, (
            f"No SONAME entry found in ELF dynamic section:\n"
            f"{result.stdout}"
        )
        soname = soname_match.group(1)
        assert soname == "libnetmon.so.2", (
            f"SONAME should be 'libnetmon.so.2' (major ABI version only "
            f"per Debian shared library policy), got '{soname}'."
        )

    def test_public_symbols_exported(self):
        """All public API symbols must appear in the dynamic symbol table."""
        self._assert_built()

        lib_path = find_versioned_lib()
        assert lib_path is not None, "libnetmon.so not found"

        result = run_cmd(["nm", "-D", "--defined-only", lib_path])
        assert result.returncode == 0, f"nm failed: {result.stderr}"

        exported_symbols = set()
        for line in result.stdout.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) >= 2:
                sym_name = parts[-1].split('@@')[0].split('@')[0]
                exported_symbols.add(sym_name)

        public_api = [
            "netmon_version",
            "netmon_check_host",
            "netmon_get_local_hostname",
            "netmon_print_info",
        ]
        for sym in public_api:
            assert sym in exported_symbols, (
                f"Public API symbol '{sym}' not found in dynamic symbol "
                f"table. Exported: {sorted(exported_symbols)}"
            )

    def test_internal_symbols_hidden(self):
        """Internal implementation symbols must NOT be exported."""
        self._assert_built()

        lib_path = find_versioned_lib()
        assert lib_path is not None, "libnetmon.so not found"

        result = run_cmd(["nm", "-D", "--defined-only", lib_path])
        assert result.returncode == 0, f"nm failed: {result.stderr}"

        exported_symbols = set()
        for line in result.stdout.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) >= 2:
                sym_name = parts[-1].split('@@')[0].split('@')[0]
                exported_symbols.add(sym_name)

        assert "resolve_hostname" not in exported_symbols, (
            "Internal symbol 'resolve_hostname' should not appear in the "
            "dynamic symbol table."
        )

    def test_versioned_symbols(self):
        """Public API symbols must carry GNU version tag NETMON_2."""
        self._assert_built()

        lib_path = find_versioned_lib()
        assert lib_path is not None, "libnetmon.so not found"

        result = run_cmd(["readelf", "-W", "--dyn-syms", lib_path])
        assert result.returncode == 0, f"readelf failed: {result.stderr}"

        public_api = [
            "netmon_version",
            "netmon_check_host",
            "netmon_get_local_hostname",
            "netmon_print_info",
        ]
        for sym in public_api:
            # Check for @@NETMON_2 (default version) in readelf output
            assert f'{sym}@@NETMON_2' in result.stdout, (
                f"Symbol '{sym}' must have GNU version tag @@NETMON_2. "
                f"A linker version script is required.\n"
                f"readelf output:\n{result.stdout}"
            )

    def test_version_definition(self):
        """Library must define a NETMON_2 version node."""
        self._assert_built()

        lib_path = find_versioned_lib()
        assert lib_path is not None, "libnetmon.so not found"

        result = run_cmd(["readelf", "-W", "-V", lib_path])
        assert result.returncode == 0, f"readelf failed: {result.stderr}"
        assert "NETMON_2" in result.stdout, (
            "NETMON_2 version node not found in .gnu.version_d. "
            "A linker version script is required.\n"
            f"readelf -V output:\n{result.stdout}"
        )

    def test_pkgconfig_path(self):
        """pkg-config file must reference netmon-v2 include directory."""
        self._assert_built()

        pc_path = None
        for p in [
            "usr/lib/pkgconfig/netmon.pc",
            "usr/lib/x86_64-linux-gnu/pkgconfig/netmon.pc",
        ]:
            full = os.path.join(INSTALL_DIR, p)
            if os.path.exists(full):
                pc_path = full
                break

        assert pc_path is not None, "netmon.pc not found in install tree"

        with open(pc_path, 'r') as f:
            content = f.read()

        cflags_line = None
        for line in content.split('\n'):
            if line.startswith('Cflags:'):
                cflags_line = line
                break

        assert cflags_line is not None, "No Cflags line in netmon.pc"
        assert 'netmon-v2' in cflags_line, (
            f"Cflags should reference 'netmon-v2' directory, "
            f"got: {cflags_line}"
        )

    def test_runtime(self):
        """Library functions must work correctly at runtime."""
        self._assert_built()

        lib_dir = find_lib_dir()
        assert lib_dir is not None, "Cannot find libnetmon.so directory"

        inc_dir = os.path.join(INSTALL_DIR, "usr/include")

        test_c = '/tmp/test_netmon_runtime.c'
        with open(test_c, 'w') as f:
            f.write("""
#include <stdio.h>
#include <string.h>
#include "netmon-v2/api.h"

int main(void) {
    const char *v = netmon_version();
    if (!v || strlen(v) == 0) {
        fprintf(stderr, "FAIL: netmon_version returned empty\\n");
        return 1;
    }

    char hostname[256];
    memset(hostname, 0, sizeof(hostname));
    int ret = netmon_get_local_hostname(hostname, sizeof(hostname));
    if (ret != 0) {
        fprintf(stderr, "FAIL: netmon_get_local_hostname returned %d\\n", ret);
        return 1;
    }
    if (strlen(hostname) == 0) {
        fprintf(stderr, "FAIL: hostname is empty\\n");
        return 1;
    }

    printf("OK version=%s hostname=%s\\n", v, hostname);
    return 0;
}
""")

        r = run_cmd([
            "gcc", test_c, "-o", "/tmp/test_netmon_runtime",
            f"-I{inc_dir}", f"-L{lib_dir}", "-lnetmon",
            f"-Wl,-rpath,{lib_dir}",
        ])
        assert r.returncode == 0, (
            f"Test program compilation/linking failed:\n{r.stderr}"
        )

        r = run_cmd(["/tmp/test_netmon_runtime"])
        assert r.returncode == 0, (
            f"Runtime test failed:\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "OK" in r.stdout, f"Unexpected output: {r.stdout}"
