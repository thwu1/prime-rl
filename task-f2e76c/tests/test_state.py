"""
Verification tests for libnetshaper bug fixes.

Runs every test case under both a normal build and an AddressSanitizer
build, then verifies the new batch_add_update_same test exists in source.

"""

import subprocess
import os
import pytest

BUILD_DIR = "/app"

ALL_TESTS = [
    "handle_queue_no_id",
    "handle_netdev_nonzero_id",
    "handle_id_overflow",
    "node_active_polarity",
    "group_duplicate_leaves",
    "batch_add_before_delete",
    "replace_child_reset",
    "subtree_stats_basic",
    "batch_add_update_same",
]


def _build(cflags=None, ldflags=None):
    cmd = ["make", "-C", BUILD_DIR, "clean", "all"]
    if cflags:
        cmd.append(f"CFLAGS={cflags}")
    if ldflags:
        cmd.append(f"LDFLAGS={ldflags}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (
        f"Build failed (rc={r.returncode}):\n"
        f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )


def _run(test_name, env=None):
    return subprocess.run(
        [f"{BUILD_DIR}/test_shaper", test_name],
        capture_output=True,
        text=True,
        timeout=30,
        env=env if env else os.environ.copy(),
    )


# -- Phase 1: Normal build ------------------------------------------------

class TestNormalBuild:
    @classmethod
    def setup_class(cls):
        _build()

    @pytest.mark.parametrize("name", ALL_TESTS)
    def test_case(self, name):
        r = _run(name)
        assert r.returncode == 0, (
            f"FAIL ({name}):\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )


# -- Phase 2: AddressSanitizer build --------------------------------------

class TestAsanBuild:
    @classmethod
    def setup_class(cls):
        _build(
            cflags=(
                "-Wall -Wextra -std=c11 -g -O0 "
                "-fsanitize=address -fno-omit-frame-pointer"
            ),
            ldflags="-fsanitize=address -static-libasan",
        )

    @pytest.mark.parametrize("name", ALL_TESTS)
    def test_case(self, name):
        env = os.environ.copy()
        env["ASAN_OPTIONS"] = "detect_leaks=0"
        r = _run(name, env=env)
        assert r.returncode == 0, (
            f"ASAN FAIL ({name}):\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )


# -- Phase 3: Source verification ------------------------------------------

class TestNewTestExists:
    """Verify the agent added the required new test case."""

    def test_function_defined(self):
        with open(f"{BUILD_DIR}/test_shaper.c") as f:
            src = f.read()
        assert "test_batch_add_update_same" in src, (
            "test_shaper.c must contain a test_batch_add_update_same function"
        )

    def test_registered_in_table(self):
        with open(f"{BUILD_DIR}/test_shaper.c") as f:
            src = f.read()
        assert '"batch_add_update_same"' in src, (
            "batch_add_update_same must be registered in test_table"
        )

    def test_has_assertions(self):
        with open(f"{BUILD_DIR}/test_shaper.c") as f:
            src = f.read()
        idx = src.find("test_batch_add_update_same")
        assert idx >= 0, "Cannot find test_batch_add_update_same"
        snippet = src[idx : idx + 1500]
        assert "ASSERT" in snippet, (
            "batch_add_update_same must contain at least one ASSERT macro"
        )
