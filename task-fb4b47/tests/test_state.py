
import subprocess
import os
import csv
import io
import pytest

CANARY_STORAGE = "/tmp/magma_test_canaries.bin"


def build(canaries=False, fixes=False):
    """Build the project with specified flags."""
    subprocess.run(["make", "clean"], cwd="/app", capture_output=True)
    for f in ["/app/imgutil_driver", "/app/monitor"]:
        if os.path.exists(f):
            os.remove(f)
    if os.path.exists(CANARY_STORAGE):
        os.remove(CANARY_STORAGE)

    cmd = ["make"]
    if canaries:
        cmd.append("CANARIES=1")
    if fixes:
        cmd.append("FIXES=1")

    result = subprocess.run(cmd, cwd="/app", capture_output=True, text=True)
    assert result.returncode == 0, f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def run_driver(test_id):
    """Run the driver with a specific test and return the process result."""
    env = os.environ.copy()
    env["MAGMA_STORAGE"] = CANARY_STORAGE
    result = subprocess.run(
        ["/app/imgutil_driver", str(test_id)],
        cwd="/app", capture_output=True, text=True, env=env,
        timeout=30
    )
    return result


def run_monitor():
    """Run the monitor and return parsed bug data as dict."""
    env = os.environ.copy()
    env["MAGMA_STORAGE"] = CANARY_STORAGE
    result = subprocess.run(
        ["/app/monitor"],
        cwd="/app", capture_output=True, text=True, env=env,
        timeout=10
    )
    assert result.returncode == 0, f"Monitor failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    reader = csv.DictReader(io.StringIO(result.stdout))
    bugs = {}
    for row in reader:
        bugs[row["bug_id"]] = {
            "reached": int(row["reached"]),
            "triggered": int(row["triggered"])
        }
    return bugs


class TestCreatedFiles:
    """Verify all required files were created by the agent."""

    def test_canary_header_created(self):
        assert os.path.exists("/app/magma/canary.h"), \
            "magma/canary.h must be created"

    def test_canary_source_created(self):
        assert os.path.exists("/app/magma/canary.c"), \
            "magma/canary.c must be created"

    def test_monitor_source_created(self):
        assert os.path.exists("/app/magma/monitor.c"), \
            "magma/monitor.c must be created"

    def test_canary_header_has_macros(self):
        """canary.h must define MAGMA_LOG, MAGMA_AND, MAGMA_OR macros."""
        with open("/app/magma/canary.h") as f:
            content = f.read()
        assert "MAGMA_LOG" in content, "canary.h missing MAGMA_LOG macro"
        assert "MAGMA_AND" in content, "canary.h missing MAGMA_AND macro"
        assert "MAGMA_OR" in content, "canary.h missing MAGMA_OR macro"
        assert "MAGMA_ENABLE_CANARIES" in content, \
            "canary.h must conditionally define MAGMA_LOG based on MAGMA_ENABLE_CANARIES"

    def test_imgutil_instrumented(self):
        """imgutil.c must contain MAGMA_LOG calls and preprocessor guards."""
        with open("/app/src/imgutil.c") as f:
            content = f.read()
        assert "MAGMA_LOG" in content, \
            "imgutil.c does not contain MAGMA_LOG instrumentation"
        assert "MAGMA_ENABLE_FIXES" in content, \
            "imgutil.c missing MAGMA_ENABLE_FIXES guards"
        assert "MAGMA_ENABLE_CANARIES" in content, \
            "imgutil.c missing MAGMA_ENABLE_CANARIES guards"
        assert '#include "canary.h"' in content or "#include \"canary.h\"" in content, \
            "imgutil.c must include canary.h"

    def test_makefile_has_modes(self):
        """Makefile must support CANARIES and FIXES flags."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "CANARIES" in content, "Makefile missing CANARIES support"
        assert "FIXES" in content or "MAGMA_ENABLE_FIXES" in content, \
            "Makefile missing FIXES support"
        assert "monitor" in content, "Makefile missing monitor target"


class TestBuildModes:
    """Verify compilation succeeds in all modes."""

    def test_build_plain(self):
        build(canaries=False, fixes=False)
        assert os.path.exists("/app/imgutil_driver"), "imgutil_driver not built"
        assert os.path.exists("/app/monitor"), "monitor not built in plain mode"

    def test_build_canaries(self):
        build(canaries=True, fixes=False)
        assert os.path.exists("/app/imgutil_driver"), \
            "imgutil_driver not built with CANARIES=1"
        assert os.path.exists("/app/monitor"), "monitor not built"

    def test_build_canaries_fixes(self):
        build(canaries=True, fixes=True)
        assert os.path.exists("/app/imgutil_driver"), \
            "imgutil_driver not built with CANARIES=1 FIXES=1"


class TestCanaryBehavior:
    """Verify correct BUG_R/BUG_T counts for each bug."""

    @classmethod
    def setup_class(cls):
        build(canaries=True, fixes=False)

    def _run_and_monitor(self, bug_num):
        if os.path.exists(CANARY_STORAGE):
            os.remove(CANARY_STORAGE)
        result = run_driver(bug_num)
        assert result.returncode == 0, \
            f"Driver failed for bug {bug_num}: {result.stderr}"
        return run_monitor()

    def test_bug001_integer_overflow(self):
        """BUG001: single call, overflow detected -> reached=1, triggered=1"""
        bugs = self._run_and_monitor(1)
        assert "BUG001" in bugs, "BUG001 not found in monitor output"
        assert bugs["BUG001"]["reached"] == 1, \
            f"BUG001 reached={bugs['BUG001']['reached']}, expected 1"
        assert bugs["BUG001"]["triggered"] == 1, \
            f"BUG001 triggered={bugs['BUG001']['triggered']}, expected 1"

    def test_bug002_oob_read(self):
        """BUG002: 3 pixels, 1 OOB -> reached=3, triggered=1"""
        bugs = self._run_and_monitor(2)
        assert "BUG002" in bugs, "BUG002 not found in monitor output"
        assert bugs["BUG002"]["reached"] == 3, \
            f"BUG002 reached={bugs['BUG002']['reached']}, expected 3"
        assert bugs["BUG002"]["triggered"] == 1, \
            f"BUG002 triggered={bugs['BUG002']['triggered']}, expected 1"

    def test_bug003_off_by_one(self):
        """BUG003: 8 iterations (i=1..8), OOB on last -> reached=8, triggered=1"""
        bugs = self._run_and_monitor(3)
        assert "BUG003" in bugs, "BUG003 not found in monitor output"
        assert bugs["BUG003"]["reached"] == 8, \
            f"BUG003 reached={bugs['BUG003']['reached']}, expected 8"
        assert bugs["BUG003"]["triggered"] == 1, \
            f"BUG003 triggered={bugs['BUG003']['triggered']}, expected 1"

    def test_bug004_buffer_overflow(self):
        """BUG004: 40 chars, OOB starts at write_pos=16 -> reached=40, triggered=24"""
        bugs = self._run_and_monitor(4)
        assert "BUG004" in bugs, "BUG004 not found in monitor output"
        assert bugs["BUG004"]["reached"] == 40, \
            f"BUG004 reached={bugs['BUG004']['reached']}, expected 40"
        assert bugs["BUG004"]["triggered"] == 24, \
            f"BUG004 triggered={bugs['BUG004']['triggered']}, expected 24"

    def test_bug005_sign_confusion(self):
        """BUG005: single call, negative stated_len -> reached=1, triggered=1"""
        bugs = self._run_and_monitor(5)
        assert "BUG005" in bugs, "BUG005 not found in monitor output"
        assert bugs["BUG005"]["reached"] == 1, \
            f"BUG005 reached={bugs['BUG005']['reached']}, expected 1"
        assert bugs["BUG005"]["triggered"] == 1, \
            f"BUG005 triggered={bugs['BUG005']['triggered']}, expected 1"


class TestFixesMode:
    """With FIXES enabled, no bugs should be reached or triggered."""

    def test_all_bugs_fixed(self):
        build(canaries=True, fixes=True)
        if os.path.exists(CANARY_STORAGE):
            os.remove(CANARY_STORAGE)

        env = os.environ.copy()
        env["MAGMA_STORAGE"] = CANARY_STORAGE
        for i in range(1, 6):
            subprocess.run(
                ["/app/imgutil_driver", str(i)],
                cwd="/app", capture_output=True, text=True, env=env,
                timeout=30
            )

        if os.path.exists(CANARY_STORAGE):
            result = subprocess.run(
                ["/app/monitor"],
                cwd="/app", capture_output=True, text=True, env=env,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                reader = csv.DictReader(io.StringIO(result.stdout))
                for row in reader:
                    assert int(row["triggered"]) == 0, \
                        f"Bug {row['bug_id']} triggered={row['triggered']} in FIXES mode"
                    assert int(row["reached"]) == 0, \
                        f"Bug {row['bug_id']} reached={row['reached']} in FIXES mode"


class TestMonitorFormat:
    """Monitor output must be valid CSV with correct header."""

    def test_csv_header(self):
        build(canaries=True, fixes=False)
        if os.path.exists(CANARY_STORAGE):
            os.remove(CANARY_STORAGE)

        run_driver(1)

        env = os.environ.copy()
        env["MAGMA_STORAGE"] = CANARY_STORAGE
        result = subprocess.run(
            ["/app/monitor"],
            cwd="/app", capture_output=True, text=True, env=env,
            timeout=10
        )
        assert result.returncode == 0, "Monitor returned non-zero exit code"

        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 2, "Monitor must output header + at least one data row"

        header = lines[0].strip()
        assert header == "bug_id,reached,triggered", \
            f"Header must be 'bug_id,reached,triggered', got '{header}'"

    def test_csv_parseable(self):
        """All rows must have exactly 3 fields with integer counts."""
        build(canaries=True, fixes=False)
        if os.path.exists(CANARY_STORAGE):
            os.remove(CANARY_STORAGE)

        env = os.environ.copy()
        env["MAGMA_STORAGE"] = CANARY_STORAGE
        for i in range(1, 6):
            subprocess.run(
                ["/app/imgutil_driver", str(i)],
                cwd="/app", capture_output=True, text=True, env=env,
                timeout=30
            )

        result = subprocess.run(
            ["/app/monitor"],
            cwd="/app", capture_output=True, text=True, env=env,
            timeout=10
        )
        assert result.returncode == 0

        reader = csv.DictReader(io.StringIO(result.stdout))
        rows = list(reader)
        assert len(rows) == 5, f"Expected 5 bug entries, got {len(rows)}"
        for row in rows:
            assert "bug_id" in row, "Missing bug_id column"
            assert "reached" in row, "Missing reached column"
            assert "triggered" in row, "Missing triggered column"
            int(row["reached"])
            int(row["triggered"])


class TestAntiShortCircuit:
    """MAGMA_AND/MAGMA_OR must evaluate both operands."""

    @classmethod
    def setup_class(cls):
        build(canaries=True, fixes=False)

    def test_magma_and_no_shortcircuit(self):
        test_src = r"""
#include <stdio.h>
#include "canary.h"

int counter = 0;

int side_effect(int val) {
    counter++;
    return val;
}

int main(void) {
    counter = 0;
    int r = MAGMA_AND(side_effect(0), side_effect(1));
    printf("and_counter=%d and_result=%d\n", counter, r);

    counter = 0;
    r = MAGMA_OR(side_effect(1), side_effect(1));
    printf("or_counter=%d or_result=%d\n", counter, r);

    return 0;
}
"""
        with open("/tmp/test_sc.c", "w") as f:
            f.write(test_src)

        result = subprocess.run(
            ["gcc", "-DMAGMA_ENABLE_CANARIES", "-I/app/magma",
             "-o", "/tmp/test_sc",
             "/tmp/test_sc.c", "/app/magma/canary.c", "/app/magma/storage.c"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Compilation failed: {result.stderr}"

        env = os.environ.copy()
        env["MAGMA_STORAGE"] = "/tmp/magma_sc_test.bin"
        if os.path.exists(env["MAGMA_STORAGE"]):
            os.remove(env["MAGMA_STORAGE"])

        result = subprocess.run(
            ["/tmp/test_sc"],
            capture_output=True, text=True, env=env,
            timeout=10
        )
        assert result.returncode == 0, f"Test program failed: {result.stderr}"

        lines = result.stdout.strip().split("\n")
        for line in lines:
            parts = dict(item.split("=") for item in line.split())
            if "and_counter" in parts:
                assert int(parts["and_counter"]) == 2, \
                    f"MAGMA_AND short-circuited: counter={parts['and_counter']}, expected 2"
                assert int(parts["and_result"]) == 0, \
                    f"MAGMA_AND(0,1) should return 0, got {parts['and_result']}"
            if "or_counter" in parts:
                assert int(parts["or_counter"]) == 2, \
                    f"MAGMA_OR short-circuited: counter={parts['or_counter']}, expected 2"
                assert int(parts["or_result"]) == 1, \
                    f"MAGMA_OR(1,1) should return 1, got {parts['or_result']}"
