
import json
import os
import subprocess
import pytest

PROBES_DIR = "/app/probes"
REPORT_PATH = "/app/conformance_report.json"
INITIAL_REPORT_PATH = "/app/initial_report.json"
STANDARDS = ["c11", "c17", "c2x"]


def _compile_check(probe_path, std, pedantic_errors=False):
    """Try to compile a probe file, return True if exit code 0."""
    cmd = ["gcc", "-std={}".format(std), "-fsyntax-only"]
    if pedantic_errors:
        cmd.append("-pedantic-errors")
    cmd.append(probe_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def _classify(probe_path, std):
    """Classify a probe as standard/extension/rejected using two-stage compilation."""
    if _compile_check(probe_path, std, pedantic_errors=True):
        return "standard"
    if _compile_check(probe_path, std, pedantic_errors=False):
        return "extension"
    return "rejected"


def _run_probe(probe_path, std):
    """Compile and run a probe, return (exit_code, stdout) or (None, None)."""
    binary = "/tmp/_verify_probe"
    compile_cmd = ["gcc", "-std={}".format(std), "-o", binary, probe_path]
    result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None, None
    try:
        run_result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
        return run_result.returncode, run_result.stdout
    except subprocess.TimeoutExpired:
        return None, None
    finally:
        if os.path.exists(binary):
            os.remove(binary)


def _get_probe_names():
    """Get sorted list of probe names (without .c extension)."""
    return sorted(
        f[:-2] for f in os.listdir(PROBES_DIR) if f.endswith(".c")
    )


@pytest.fixture(scope="session")
def report():
    assert os.path.isfile(REPORT_PATH), "Report not found: {}".format(REPORT_PATH)
    with open(REPORT_PATH) as f:
        return json.load(f)


class TestReportStructure:
    def test_report_is_dict(self, report):
        assert isinstance(report, dict)

    def test_has_compiler_info(self, report):
        assert "compiler" in report
        assert "version" in report["compiler"]
        assert isinstance(report["compiler"]["version"], str)
        assert len(report["compiler"]["version"]) > 0

    def test_has_probes_section(self, report):
        assert "probes" in report
        assert isinstance(report["probes"], dict)

    def test_all_probes_present(self, report):
        expected = set(_get_probe_names())
        actual = set(report["probes"].keys())
        missing = expected - actual
        assert not missing, "Missing probes: {}".format(missing)

    def test_probe_has_description(self, report):
        for name, data in report["probes"].items():
            assert "description" in data, "{}: missing description".format(name)
            assert isinstance(data["description"], str)
            assert len(data["description"]) > 0, "{}: empty description".format(name)

    def test_probe_result_fields(self, report):
        for name, data in report["probes"].items():
            assert "results" in data, "{}: missing results".format(name)
            for std in STANDARDS:
                assert std in data["results"], "{}: missing {}".format(name, std)
                r = data["results"][std]
                assert "classification" in r, "{}/{}: missing classification".format(
                    name, std
                )
                assert r["classification"] in (
                    "standard",
                    "extension",
                    "rejected",
                ), "{}/{}: invalid classification '{}'".format(
                    name, std, r["classification"]
                )

    def test_has_summary(self, report):
        assert "summary" in report
        assert "total_probes" in report["summary"]

    def test_summary_keys_present(self, report):
        summary = report["summary"]
        for std in STANDARDS:
            for cat in ["standard", "extension", "rejected"]:
                key = "{}_{}".format(std, cat)
                assert key in summary, "Missing summary key: {}".format(key)


class TestClassificationAccuracy:
    def test_all_classifications_match_gcc(self, report):
        """Independently compile each probe and verify classifications match."""
        errors = []
        for name in _get_probe_names():
            probe_path = os.path.join(PROBES_DIR, name + ".c")
            for std in STANDARDS:
                expected = _classify(probe_path, std)
                actual = report["probes"][name]["results"][std]["classification"]
                if expected != actual:
                    errors.append(
                        "  {}/{}: expected={}, actual={}".format(
                            name, std, expected, actual
                        )
                    )
        assert not errors, "Classification mismatches:\n" + "\n".join(errors)

    def test_c17_matches_c11(self, report):
        """C17 introduced no new language features; classifications should match C11."""
        mismatches = []
        for name, data in report["probes"].items():
            c11_cls = data["results"]["c11"]["classification"]
            c17_cls = data["results"]["c17"]["classification"]
            if c11_cls != c17_cls:
                mismatches.append(
                    "  {}: c11={}, c17={}".format(name, c11_cls, c17_cls)
                )
        assert not mismatches, (
            "C17 should match C11:\n" + "\n".join(mismatches)
        )


class TestSummaryAccuracy:
    def test_counts_match_probe_data(self, report):
        """Summary counts must equal aggregated per-probe classifications."""
        for std in STANDARDS:
            counts = {"standard": 0, "extension": 0, "rejected": 0}
            for data in report["probes"].values():
                cls = data["results"][std]["classification"]
                counts[cls] += 1
            summary = report["summary"]
            for cat, count in counts.items():
                key = "{}_{}".format(std, cat)
                assert summary[key] == count, (
                    "Summary {}: expected {}, got {}".format(key, count, summary[key])
                )

    def test_total_probes(self, report):
        expected = len(_get_probe_names())
        assert report["summary"]["total_probes"] == expected


class TestRuntimeBehavior:
    def test_sizeof_true_compiles_all_modes(self, report):
        """sizeof_true.c uses only stdbool.h/stdio.h and should be standard in all modes."""
        if "sizeof_true" not in report["probes"]:
            pytest.skip("sizeof_true probe missing from report")
        for std in STANDARDS:
            cls = report["probes"]["sizeof_true"]["results"][std]["classification"]
            assert cls == "standard", (
                "sizeof_true should be 'standard' in {}, got '{}'".format(std, cls)
            )

    def test_sizeof_true_output_captured(self, report):
        """sizeof_true should have captured runtime output for c11 and c2x."""
        if "sizeof_true" not in report["probes"]:
            pytest.skip("sizeof_true probe missing from report")
        for std in ["c11", "c2x"]:
            r = report["probes"]["sizeof_true"]["results"][std]
            assert r.get("output") is not None and len(
                str(r["output"]).strip()
            ) > 0, "sizeof_true/{}: output not captured".format(std)

    def test_sizeof_true_differs_across_standards(self):
        """sizeof(true) should differ between C11 (int=4) and C23 (bool=1)."""
        probe_path = os.path.join(PROBES_DIR, "sizeof_true.c")
        _, c11_out = _run_probe(probe_path, "c11")
        _, c2x_out = _run_probe(probe_path, "c2x")
        if c11_out is None or c2x_out is None:
            pytest.skip("Could not run sizeof_true probe")
        c11_val = int(c11_out.strip())
        c2x_val = int(c2x_out.strip())
        assert c11_val != c2x_val, (
            "sizeof(true) should differ: C11={}, C23={}".format(c11_val, c2x_val)
        )

    def test_compilable_probes_have_runtime_data(self, report):
        """Probes that compile (standard or extension) should have runtime data."""
        missing = []
        for name, data in report["probes"].items():
            for std in STANDARDS:
                r = data["results"][std]
                if r["classification"] != "rejected":
                    if r.get("runs") is None or r.get("exit_code") is None:
                        missing.append("{}/{}".format(name, std))
        assert not missing, (
            "Compilable probes should have runtime data:\n  "
            + "\n  ".join(missing)
        )

    def test_c2x_standard_probes_run_successfully(self, report):
        """Probes classified as standard in c2x should run with exit code 0."""
        failures = []
        for name, data in report["probes"].items():
            r = data["results"]["c2x"]
            if r["classification"] == "standard":
                runs = r.get("runs")
                exit_code = r.get("exit_code")
                if runs is not True:
                    failures.append("  {}: not run".format(name))
                elif exit_code != 0:
                    failures.append(
                        "  {}: exit_code={}".format(name, exit_code)
                    )
        assert not failures, (
            "C2x standard probes should run successfully:\n" + "\n".join(failures)
        )


class TestNotCopiedFromInitial:
    def test_report_differs_from_initial(self, report):
        """Corrected report must differ from the known-buggy initial report."""
        if not os.path.isfile(INITIAL_REPORT_PATH):
            pytest.skip("initial_report.json not found")
        with open(INITIAL_REPORT_PATH) as f:
            initial = json.load(f)
        differences = 0
        for name in _get_probe_names():
            if name not in initial.get("probes", {}):
                differences += 1
                continue
            if name not in report.get("probes", {}):
                continue
            for std in STANDARDS:
                init_r = initial["probes"][name]["results"].get(std, {})
                new_r = report["probes"][name]["results"].get(std, {})
                if init_r.get("classification") != new_r.get("classification"):
                    differences += 1
                if init_r.get("output") != new_r.get("output"):
                    differences += 1
                if init_r.get("runs") != new_r.get("runs"):
                    differences += 1
        assert differences >= 5, (
            "Report should differ from initial_report.json in at least 5 ways "
            "(initial has known errors); found only {} differences".format(
                differences
            )
        )

    def test_has_extension_classifications(self, report):
        """Report should contain 'extension' classifications for C11/C17 probes."""
        extension_count = 0
        for data in report["probes"].values():
            for std in ["c11", "c17"]:
                if data["results"][std]["classification"] == "extension":
                    extension_count += 1
        assert extension_count >= 2, (
            "Expected at least 2 'extension' classifications in C11/C17 modes, "
            "found {}".format(extension_count)
        )


class TestAnalyzerScript:
    def test_analyzer_exists(self):
        assert os.path.isfile("/app/analyzer.py"), "analyzer.py not found"

    def test_analyzer_valid_python(self):
        result = subprocess.run(
            [
                "python3",
                "-c",
                "import py_compile; py_compile.compile('/app/analyzer.py', doraise=True)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "Syntax error: {}".format(result.stderr)
