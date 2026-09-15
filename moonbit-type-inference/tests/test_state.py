
import subprocess
import os
import re
import shutil


MOON_ENV = os.environ.copy()
MOON_ENV["PATH"] = "/root/.moon/bin:" + MOON_ENV.get("PATH", "")


def _ensure_moon():
    """Install moon toolchain if not already present.

    Uses Python tarfile with filter='data' to avoid chmod failures
    in container runtimes that restrict permission changes.
    """
    moon_bin = "/root/.moon/bin/moon"
    if not os.path.isfile(moon_bin):
        # Replicate the official install steps manually, using Python tarfile
        # to extract archives without setting permissions (avoids chmod errors
        # on overlayfs / restricted container filesystems).
        install_script = r"""
set -e
mkdir -p /root/.moon/bin /root/.moon/lib

echo "Downloading moonbit ..."
curl -fsSL "https://cli.moonbitlang.com/binaries/latest/moonbit-linux-x86_64.tar.gz" -o /tmp/moonbit.tar.gz
python3 -c "import tarfile; tarfile.open('/tmp/moonbit.tar.gz').extractall('/root/.moon', filter='data')"
rm -f /tmp/moonbit.tar.gz
find /root/.moon/bin -type f -exec chmod +x {} +
find /root/.moon/bin/internal -type f -exec chmod +x {} + 2>/dev/null || true

echo "Downloading core ..."
curl -fsSL "https://cli.moonbitlang.com/cores/core-latest.tar.gz" -o /tmp/core.tar.gz
python3 -c "import tarfile; tarfile.open('/tmp/core.tar.gz').extractall('/root/.moon/lib', filter='data')"
rm -f /tmp/core.tar.gz

echo "Bundling core ..."
export PATH="/root/.moon/bin:${PATH}"
/root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --all
/root/.moon/bin/moon -C /root/.moon/lib/core bundle --warn-list -a --target wasm-gc --quiet

echo "Done."
"""
        subprocess.run(
            ["bash", "-c", install_script],
            env=MOON_ENV,
            timeout=300,
            check=True,
        )
    assert os.path.isfile(moon_bin), f"moon binary not found at {moon_bin} after install"


def test_project_structure():
    """Verify the MoonBit project has the correct structure."""
    assert os.path.exists("/app/moon.mod.json"), "moon.mod.json missing"
    # Accept either moon.pkg.json (current) or moon.pkg (legacy)
    assert os.path.exists("/app/moon.pkg.json") or os.path.exists(
        "/app/moon.pkg"
    ), "moon.pkg.json (or moon.pkg) missing"
    assert os.path.exists("/app/hm_wbtest.mbt"), "hm_wbtest.mbt missing"
    # At least one implementation .mbt file must exist
    mbt_files = [
        f
        for f in os.listdir("/app")
        if f.endswith(".mbt") and f != "hm_wbtest.mbt"
    ]
    assert len(mbt_files) > 0, (
        "No implementation .mbt files found in /app/. "
        "Expected at least one file implementing infer_type."
    )


def test_moon_build():
    """Verify the project builds successfully with moon build."""
    _ensure_moon()
    result = subprocess.run(
        ["/root/.moon/bin/moon", "build"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
        env=MOON_ENV,
    )
    assert result.returncode == 0, (
        f"moon build failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_moon_test_passes():
    """Restore original tests and verify all 15 pass via moon test."""
    _ensure_moon()
    # Restore original test file to prevent tampering
    shutil.copy("/opt/original_tests/hm_wbtest.mbt", "/app/hm_wbtest.mbt")

    result = subprocess.run(
        ["/root/.moon/bin/moon", "test"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=180,
        env=MOON_ENV,
    )
    combined = result.stdout + "\n" + result.stderr

    # Check no failures
    assert "failed: 0" in combined, (
        f"Some tests failed.\nOutput:\n{combined}"
    )

    # Check at least 15 tests passed
    match = re.search(r"passed:\s*(\d+)", combined)
    assert match is not None, (
        f"Could not find pass count in output:\n{combined}"
    )
    passed = int(match.group(1))
    assert passed >= 15, (
        f"Expected at least 15 tests to pass, got {passed}.\n"
        f"Output:\n{combined}"
    )
