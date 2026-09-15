
"""
Tests for MAGMA ground-truth canary instrumentation of libmfp.

Verifies that:
  - All 4 patches exist and follow MAGMA format conventions
  - Patched source compiles in both canary and fixed modes
  - Canary mode correctly detects each bug being triggered
  - Fixed mode prevents all crashes
"""

import pytest
import subprocess
import os
import shutil
import tempfile
import re

BUG_IDS = ["MFP001", "MFP002", "MFP003", "MFP004"]
CORPUS_DIR = "/app/corpus"
PATCHES_DIR = "/app/patches"
SRC_BACKUP = "/app/src_backup"
APPLY_SCRIPT = "/app/scripts/apply_patches.sh"


def parse_canary_output(csv_path):
    """Parse canary output CSV into {bug_id: {'R': count, 'T': count}}."""
    result = {}
    if not os.path.exists(csv_path):
        return result
    with open(csv_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            try:
                value = int(parts[1].strip())
            except ValueError:
                continue
            if key.endswith('_R'):
                bug = key[:-2]
                result.setdefault(bug, {'R': 0, 'T': 0})
                result[bug]['R'] = value
            elif key.endswith('_T'):
                bug = key[:-2]
                result.setdefault(bug, {'R': 0, 'T': 0})
                result[bug]['T'] = value
    return result


@pytest.fixture(scope="session")
def workspace():
    """Build patched binaries in both canary and fixed modes."""
    ws = tempfile.mkdtemp(prefix="magma_test_")
    info = {"ws": ws}

    # --- Canary build ---
    canary_src = os.path.join(ws, "canary_src")
    shutil.copytree(SRC_BACKUP, canary_src)

    result = subprocess.run(
        ["bash", APPLY_SCRIPT, PATCHES_DIR, canary_src],
        capture_output=True, text=True, timeout=30
    )
    info["patches_applied"] = result.returncode == 0
    info["patch_stderr"] = result.stderr

    canary_bin = os.path.join(ws, "mfp_canary")
    info["canary_bin"] = canary_bin
    info["canary_built"] = False

    if info["patches_applied"]:
        result = subprocess.run(
            ["gcc", "-Wall", "-g", "-O0", "-DMAGMA_ENABLE_CANARIES",
             "-include", os.path.join(canary_src, "canary.h"),
             "-I", canary_src,
             os.path.join(canary_src, "mfp.c"),
             os.path.join(canary_src, "driver.c"),
             os.path.join(canary_src, "canary.c"),
             "-o", canary_bin],
            capture_output=True, text=True, timeout=30
        )
        info["canary_built"] = result.returncode == 0
        info["canary_build_stderr"] = result.stderr

    # --- Fixed build ---
    fixed_src = os.path.join(ws, "fixed_src")
    shutil.copytree(SRC_BACKUP, fixed_src)

    info["fixed_bin"] = os.path.join(ws, "mfp_fixed")
    info["fixed_built"] = False

    if info["patches_applied"]:
        subprocess.run(
            ["bash", APPLY_SCRIPT, PATCHES_DIR, fixed_src],
            capture_output=True, text=True, timeout=30
        )
        result = subprocess.run(
            ["gcc", "-Wall", "-g", "-O0", "-DMAGMA_ENABLE_FIXES",
             "-I", fixed_src,
             os.path.join(fixed_src, "mfp.c"),
             os.path.join(fixed_src, "driver.c"),
             "-o", info["fixed_bin"]],
            capture_output=True, text=True, timeout=30
        )
        info["fixed_built"] = result.returncode == 0
        info["fixed_build_stderr"] = result.stderr

    yield info

    shutil.rmtree(ws, ignore_errors=True)


# ── Patch existence ──────────────────────────────────────────────────

class TestPatchesExist:
    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_patch_file_exists(self, bug_id):
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        assert os.path.exists(path), f"Missing patch file: {path}"


# ── Patch format ─────────────────────────────────────────────────────

class TestPatchFormat:
    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_has_enable_fixes(self, bug_id):
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        if not os.path.exists(path):
            pytest.skip(f"Patch {bug_id} not found")
        content = open(path).read()
        assert "MAGMA_ENABLE_FIXES" in content

    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_has_enable_canaries(self, bug_id):
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        if not os.path.exists(path):
            pytest.skip(f"Patch {bug_id} not found")
        content = open(path).read()
        assert "MAGMA_ENABLE_CANARIES" in content

    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_has_magma_log(self, bug_id):
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        if not os.path.exists(path):
            pytest.skip(f"Patch {bug_id} not found")
        content = open(path).read()
        assert "MAGMA_LOG" in content

    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_has_bug_token(self, bug_id):
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        if not os.path.exists(path):
            pytest.skip(f"Patch {bug_id} not found")
        content = open(path).read()
        assert "%MAGMA_BUG%" in content

    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_trigger_not_trivial(self, bug_id):
        """Trigger condition must reference program state, not be a constant."""
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        if not os.path.exists(path):
            pytest.skip(f"Patch {bug_id} not found")
        content = open(path).read()
        trivial = {'1', '0', 'true', 'false'}
        matches = re.findall(r'MAGMA_LOG\s*\(\s*"[^"]*"\s*,\s*(.+?)\s*\)', content)
        assert len(matches) > 0, f"No MAGMA_LOG call found in {bug_id}"
        for cond in matches:
            stripped = cond.strip().rstrip(';').strip()
            assert stripped.lower() not in trivial, \
                f"{bug_id}: trivial trigger condition: {stripped}"

    @pytest.mark.parametrize("bug_id", BUG_IDS)
    def test_no_raw_logical_operators(self, bug_id):
        """MAGMA_LOG conditions must use MAGMA_AND/MAGMA_OR, not && or ||."""
        path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
        if not os.path.exists(path):
            pytest.skip(f"Patch {bug_id} not found")
        content = open(path).read()
        for line in content.splitlines():
            if 'MAGMA_LOG' in line:
                cleaned = line.replace('MAGMA_AND', '').replace('MAGMA_OR', '')
                assert '&&' not in cleaned, \
                    f"{bug_id}: use MAGMA_AND not && in: {line.strip()}"
                assert '||' not in cleaned, \
                    f"{bug_id}: use MAGMA_OR not || in: {line.strip()}"


# ── Build verification ───────────────────────────────────────────────

class TestBuilds:
    def test_patches_apply_cleanly(self, workspace):
        assert workspace["patches_applied"], \
            f"Patch application failed: {workspace.get('patch_stderr', '')}"

    def test_canary_mode_compiles(self, workspace):
        if not workspace["patches_applied"]:
            pytest.skip("Patches did not apply")
        assert workspace["canary_built"], \
            f"Canary build failed: {workspace.get('canary_build_stderr', '')}"

    def test_fixed_mode_compiles(self, workspace):
        if not workspace["patches_applied"]:
            pytest.skip("Patches did not apply")
        assert workspace["fixed_built"], \
            f"Fixed build failed: {workspace.get('fixed_build_stderr', '')}"


# ── Canary triggering ───────────────────────────────────────────────

class TestCanaryTriggering:
    @pytest.mark.parametrize("bug_num,bug_id", [
        ("001", "MFP001"),
        ("002", "MFP002"),
        ("003", "MFP003"),
        ("004", "MFP004"),
    ])
    def test_bug_triggered_by_crash_input(self, workspace, bug_num, bug_id, tmp_path):
        """Each crash input must trigger its corresponding bug's canary."""
        if not workspace["canary_built"]:
            pytest.skip("Canary binary not available")

        canary_csv = str(tmp_path / f"canary_{bug_num}.csv")
        corpus_file = os.path.join(CORPUS_DIR, f"crash_bug{bug_num}.mfp")
        assert os.path.exists(corpus_file), f"Corpus file missing: {corpus_file}"

        subprocess.run(
            [workspace["canary_bin"], corpus_file, canary_csv],
            capture_output=True, timeout=10
        )
        # Program may crash (bugs are active in canary mode) — that's expected.
        # The canary framework dumps data before the crash-inducing code runs.

        assert os.path.exists(canary_csv), \
            f"Canary output not written for {bug_id}. " \
            "The MAGMA_LOG oracle may not fire before the crash."

        canary_data = parse_canary_output(canary_csv)
        assert bug_id in canary_data, \
            f"{bug_id} not in canary output. Found bugs: {list(canary_data.keys())}"
        assert canary_data[bug_id]['R'] > 0, \
            f"{bug_id}: reached count is 0 — oracle never executed"
        assert canary_data[bug_id]['T'] > 0, \
            f"{bug_id}: reached {canary_data[bug_id]['R']}x but triggered 0x — " \
            "trigger condition is incorrect"


# ── Fixed-mode crash prevention ──────────────────────────────────────

class TestFixedNoCrash:
    @pytest.mark.parametrize("bug_num", ["001", "002", "003", "004"])
    def test_fixed_binary_no_signal_death(self, workspace, bug_num):
        """Fixed binary must handle all crash inputs without being killed by a signal."""
        if not workspace["fixed_built"]:
            pytest.skip("Fixed binary not available")

        corpus_file = os.path.join(CORPUS_DIR, f"crash_bug{bug_num}.mfp")

        result = subprocess.run(
            [workspace["fixed_bin"], corpus_file],
            capture_output=True, timeout=10
        )
        # returncode >= 0 means normal exit (possibly with error code).
        # returncode < 0 means killed by signal (-returncode is signal number).
        assert result.returncode >= 0, \
            f"Fixed binary crashed on crash_bug{bug_num}.mfp " \
            f"(signal {-result.returncode})"
