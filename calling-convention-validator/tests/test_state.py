
import json
import os
import glob
import subprocess
import pytest


class TestCallingConventionValidator:
    """Verify the calling convention validator output."""

    @pytest.fixture(autouse=True)
    def load_summary(self):
        path = "/app/results/summary.json"
        assert os.path.exists(path), "summary.json not found at /app/results/summary.json"
        with open(path) as f:
            self.summary = json.load(f)

    # ---- Schema and structure ----

    def test_summary_schema(self):
        """summary.json has all required top-level keys with correct types."""
        assert isinstance(self.summary.get("total_tests"), int)
        assert isinstance(self.summary.get("scenarios"), list)
        assert isinstance(self.summary.get("results"), dict)
        assert isinstance(self.summary.get("test_details"), list)

    def test_minimum_tests(self):
        """At least 50 test cases were generated."""
        assert self.summary["total_tests"] >= 50, (
            f"Only {self.summary['total_tests']} tests; need >= 50"
        )

    def test_details_count_matches_total(self):
        """test_details length equals total_tests."""
        assert len(self.summary["test_details"]) == self.summary["total_tests"]

    # ---- Scenario coverage ----

    def test_scenario_coverage(self):
        """All required ABI scenarios are represented."""
        required = {
            "integer_regs", "sse_regs", "mixed_params",
            "struct_small", "struct_medium", "struct_large",
            "return_values", "variadic",
        }
        actual = set(self.summary["scenarios"])
        missing = required - actual
        assert not missing, f"Missing required scenarios: {missing}"

    def test_scenarios_have_minimum_tests(self):
        """Each required scenario has at least 2 test cases."""
        required = {
            "integer_regs", "sse_regs", "mixed_params",
            "struct_small", "struct_medium", "struct_large",
            "return_values", "variadic",
        }
        details = self.summary["test_details"]
        for scen in required:
            count = sum(1 for d in details if d.get("scenario") == scen)
            assert count >= 2, f"Scenario '{scen}' has only {count} tests; need >= 2"

    # ---- Compiler combo results ----

    def test_result_combos_present(self):
        """All four compiler combinations are reported."""
        for combo in ["gcc_gcc", "clang_clang", "gcc_clang", "clang_gcc"]:
            assert combo in self.summary["results"], f"Missing combo: {combo}"
            r = self.summary["results"][combo]
            assert "pass" in r and "fail" in r and "error" in r, (
                f"Combo {combo} missing pass/fail/error keys"
            )

    def test_same_compiler_all_pass(self):
        """Same-compiler combos must have zero failures and zero errors."""
        for combo in ["gcc_gcc", "clang_clang"]:
            r = self.summary["results"][combo]
            assert r["fail"] == 0, f"{combo}: {r['fail']} test failures"
            assert r["error"] == 0, f"{combo}: {r['error']} compile/link errors"

    def test_result_consistency(self):
        """Pass + fail + error equals total_tests for every combo."""
        total = self.summary["total_tests"]
        for combo in ["gcc_gcc", "clang_clang", "gcc_clang", "clang_gcc"]:
            r = self.summary["results"][combo]
            s = r["pass"] + r["fail"] + r["error"]
            assert s == total, f"{combo}: {r} sums to {s}, expected {total}"

    def test_details_have_all_combos(self):
        """Every test_detail entry has results for gcc_gcc and clang_clang."""
        for detail in self.summary["test_details"]:
            assert "test_id" in detail, "test_detail missing test_id"
            assert "scenario" in detail, "test_detail missing scenario"
            for combo in ["gcc_gcc", "clang_clang"]:
                assert combo in detail, (
                    f"test_detail {detail.get('test_id')} missing {combo}"
                )

    # ---- TAP report ----

    def test_tap_report(self):
        """TAP report exists and has recognizable format."""
        path = "/app/results/report.tap"
        assert os.path.exists(path), "report.tap not found"
        with open(path) as f:
            content = f.read()
        assert len(content) > 20, "report.tap is too short"
        assert ("TAP" in content or content.lstrip().startswith("1..")), (
            "report.tap doesn't follow TAP format"
        )

    # ---- Source file verification ----

    def _find_callers(self):
        return sorted(glob.glob("/app/**/caller_*.c", recursive=True))

    def _find_callees(self):
        return sorted(glob.glob("/app/**/callee_*.c", recursive=True))

    def _find_header_dirs(self):
        dirs = set()
        for root, _, files in os.walk("/app"):
            if any(f.endswith(".h") for f in files):
                dirs.add(root)
        return dirs

    def _inc_flags(self):
        return [flag for d in self._find_header_dirs() for flag in ["-I", d]]

    def test_source_files_exist(self):
        """At least 50 caller/callee pairs were generated."""
        callers = self._find_callers()
        callees = self._find_callees()
        assert len(callers) >= 50, f"Only {len(callers)} caller files found"
        assert len(callees) >= 50, f"Only {len(callees)} callee files found"

    def test_separate_compilation_extern(self):
        """Caller files use extern declarations (separate TU)."""
        callers = self._find_callers()
        assert len(callers) > 0
        found_extern = False
        for c in callers[:5]:
            with open(c) as f:
                if "extern" in f.read():
                    found_extern = True
                    break
        assert found_extern, "No caller file contains 'extern' — likely not separate compilation"

    def test_nontrivial_callee(self):
        """Callee functions contain non-trivial parameter checks."""
        callees = self._find_callees()
        assert len(callees) > 0
        checked = 0
        for path in callees[:10]:
            with open(path) as f:
                content = f.read()
            if "!=" in content or "errors" in content:
                checked += 1
        assert checked >= 5, (
            f"Only {checked}/10 sampled callees have parameter checks"
        )

    # ---- Independent recompilation ----

    def _extract_num(self, caller_path):
        basename = os.path.basename(caller_path)
        return basename.replace("caller_", "").replace(".c", "")

    def _find_callee_for(self, caller_path):
        num = self._extract_num(caller_path)
        caller_dir = os.path.dirname(caller_path)
        candidates = [
            os.path.join(caller_dir, f"callee_{num}.c"),
        ] + glob.glob(f"/app/**/callee_{num}.c", recursive=True)
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    def test_independent_recompile_gcc(self):
        """Independently recompile and run 3 test pairs with gcc."""
        callers = self._find_callers()
        assert len(callers) >= 3, "Need at least 3 caller files"
        inc = self._inc_flags()

        for caller_path in callers[:3]:
            num = self._extract_num(caller_path)
            callee_path = self._find_callee_for(caller_path)
            assert callee_path, f"No callee found for caller_{num}.c"

            tmpdir = f"/tmp/recompile_gcc_{num}"
            os.makedirs(tmpdir, exist_ok=True)

            r1 = subprocess.run(
                ["gcc", "-c"] + inc + [caller_path, "-o", f"{tmpdir}/caller.o"],
                capture_output=True, timeout=30,
            )
            assert r1.returncode == 0, (
                f"gcc caller compile failed ({num}): {r1.stderr.decode()[:300]}"
            )

            r2 = subprocess.run(
                ["gcc", "-c"] + inc + [callee_path, "-o", f"{tmpdir}/callee.o"],
                capture_output=True, timeout=30,
            )
            assert r2.returncode == 0, (
                f"gcc callee compile failed ({num}): {r2.stderr.decode()[:300]}"
            )

            r3 = subprocess.run(
                ["gcc", f"{tmpdir}/caller.o", f"{tmpdir}/callee.o",
                 "-o", f"{tmpdir}/test", "-lm"],
                capture_output=True, timeout=30,
            )
            assert r3.returncode == 0, (
                f"gcc link failed ({num}): {r3.stderr.decode()[:300]}"
            )

            r4 = subprocess.run(
                [f"{tmpdir}/test"], capture_output=True, timeout=10,
            )
            assert r4.returncode == 0, (
                f"gcc test run failed ({num}): {r4.stdout.decode()[:300]}"
            )

    def test_cross_compiler_recompile(self):
        """Recompile one test pair with gcc caller + clang callee."""
        callers = self._find_callers()
        assert len(callers) >= 1
        inc = self._inc_flags()

        caller_path = callers[0]
        num = self._extract_num(caller_path)
        callee_path = self._find_callee_for(caller_path)
        assert callee_path, f"No callee found for caller_{num}.c"

        tmpdir = "/tmp/recompile_cross"
        os.makedirs(tmpdir, exist_ok=True)

        r1 = subprocess.run(
            ["gcc", "-c"] + inc + [caller_path, "-o", f"{tmpdir}/caller.o"],
            capture_output=True, timeout=30,
        )
        assert r1.returncode == 0, (
            f"gcc caller compile failed: {r1.stderr.decode()[:300]}"
        )

        r2 = subprocess.run(
            ["clang", "-c"] + inc + [callee_path, "-o", f"{tmpdir}/callee.o"],
            capture_output=True, timeout=30,
        )
        assert r2.returncode == 0, (
            f"clang callee compile failed: {r2.stderr.decode()[:300]}"
        )

        r3 = subprocess.run(
            ["gcc", f"{tmpdir}/caller.o", f"{tmpdir}/callee.o",
             "-o", f"{tmpdir}/test", "-lm"],
            capture_output=True, timeout=30,
        )
        assert r3.returncode == 0, (
            f"cross-link failed: {r3.stderr.decode()[:300]}"
        )

        r4 = subprocess.run(
            [f"{tmpdir}/test"], capture_output=True, timeout=10,
        )
        assert r4.returncode == 0, (
            f"cross-compiler test failed: {r4.stdout.decode()[:300]}"
        )

    # ---- Consistency between details and summary ----

    def test_details_consistent_with_summary(self):
        """Per-test pass counts in test_details match results summary."""
        for combo in ["gcc_gcc", "clang_clang", "gcc_clang", "clang_gcc"]:
            detail_pass = sum(
                1 for d in self.summary["test_details"]
                if d.get(combo) == "pass"
            )
            assert detail_pass == self.summary["results"][combo]["pass"], (
                f"{combo}: details show {detail_pass} pass but "
                f"summary shows {self.summary['results'][combo]['pass']}"
            )
