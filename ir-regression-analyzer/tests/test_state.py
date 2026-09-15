
import subprocess
import json
import re
import os
import shutil
import tempfile

import pytest


CONFIG_PATH = "/app/config.json"
MODULE_PATH = "/app/module.ll"
REPORT_PATH = "/app/report.json"

FUNC_DEF_RE = re.compile(
    r'^define\b.*?(@(?:"[^"]+"|[-a-zA-Z$._0-9]+))\s*\('
)
LABEL_RE = re.compile(
    r'^(?:[a-zA-Z$._][-a-zA-Z$._0-9]*|\d+|"[^"]*"):\s*(?:;.*)?$'
)


def _find_llvm_tool(name):
    """Locate an LLVM-18 tool binary."""
    candidates = [
        f"/usr/lib/llvm-18/bin/{name}",
        f"/usr/bin/{name}-18",
    ]
    w = shutil.which(f"{name}-18")
    if w:
        candidates.append(w)
    w = shutil.which(name)
    if w:
        candidates.append(w)
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    pytest.skip(f"LLVM tool '{name}' not found")


def _strip_ir_comment(line):
    """Remove trailing ; comment, respecting string literals."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_str = not in_str
        elif ch == ';' and not in_str:
            return line[:i].rstrip()
    return line


def _count_ir_per_function(filepath):
    """Count IR instructions per function in an LLVM IR file."""
    counts = {}
    with open(filepath) as f:
        lines = f.readlines()

    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip("\n")
        m = FUNC_DEF_RE.match(line.strip())
        if m:
            func_name = m.group(1)
            idx += 1
            count = 0
            while idx < len(lines):
                body = lines[idx].strip()
                if body == "}":
                    break
                if not body or body.startswith(";"):
                    idx += 1
                    continue
                code = _strip_ir_comment(body)
                if not code:
                    idx += 1
                    continue
                if LABEL_RE.match(code):
                    idx += 1
                    continue
                count += 1
                idx += 1
            counts[func_name] = count
        idx += 1
    return counts


def _count_asm_per_function(filepath):
    """Count assembly instructions per function in llc output."""
    counts = {}
    cur_func = None
    count = 0

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()

            if stripped.startswith(".Lfunc_end"):
                if cur_func is not None:
                    counts[cur_func] = count
                cur_func = None
                count = 0
                continue

            if (
                line
                and not line[0].isspace()
                and stripped.endswith(":")
                and not stripped.startswith(".")
                and not stripped.startswith("#")
            ):
                cur_func = stripped.rstrip(":")
                count = 0
                continue

            if cur_func is not None and line and line[0].isspace():
                if (
                    stripped
                    and not stripped.startswith(".")
                    and not stripped.startswith("#")
                    and not stripped.endswith(":")
                ):
                    count += 1

    if cur_func is not None:
        counts[cur_func] = count
    return counts


def _run_opt(opt_bin, pipeline, input_file, output_file):
    cmd = [opt_bin, f"-passes={pipeline}", "-S", input_file, "-o", output_file]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"opt failed: {result.stderr}"


def _run_llc(llc_bin, input_file, output_file, triple):
    cmd = [llc_bin, f"-mtriple={triple}", "-O2", input_file, "-o", output_file]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"llc failed: {result.stderr}"


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def opt_bin():
    return _find_llvm_tool("opt")


@pytest.fixture(scope="session")
def llc_bin():
    return _find_llvm_tool("llc")


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def report():
    assert os.path.exists(REPORT_PATH), "report.json not found at /app/report.json"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def work_dir():
    d = tempfile.mkdtemp(prefix="llvm_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session")
def expected(opt_bin, llc_bin, config, work_dir):
    """Compute ground-truth values by running LLVM tools."""
    baseline_ir = os.path.join(work_dir, "baseline.ll")
    candidate_ir = os.path.join(work_dir, "candidate.ll")
    baseline_asm = os.path.join(work_dir, "baseline.s")
    candidate_asm = os.path.join(work_dir, "candidate.s")

    _run_opt(opt_bin, config["baseline_pipeline"], MODULE_PATH, baseline_ir)
    _run_opt(opt_bin, config["candidate_pipeline"], MODULE_PATH, candidate_ir)
    _run_llc(llc_bin, baseline_ir, baseline_asm, config["target_triple"])
    _run_llc(llc_bin, candidate_ir, candidate_asm, config["target_triple"])

    b_ir = _count_ir_per_function(baseline_ir)
    c_ir = _count_ir_per_function(candidate_ir)
    b_asm = _count_asm_per_function(baseline_asm)
    c_asm = _count_asm_per_function(candidate_asm)

    # Derive pass names and prefixes from the candidate pipeline
    pass_names = [p.strip() for p in config["candidate_pipeline"].split(",")]
    prefixes = [",".join(pass_names[:i + 1]) for i in range(len(pass_names))]

    # Identify regressed functions and attribute to earliest responsible pass
    bisection = {}
    regressed = {
        fn for fn in b_ir
        if c_ir.get(fn, 0) > b_ir[fn]
    }

    for idx, prefix in enumerate(prefixes):
        if not regressed:
            break
        pfx_ir = os.path.join(work_dir, f"prefix_{idx}.ll")
        _run_opt(opt_bin, prefix, MODULE_PATH, pfx_ir)
        pfx_counts = _count_ir_per_function(pfx_ir)
        resolved = set()
        for fn in regressed:
            if pfx_counts.get(fn, 0) > b_ir[fn]:
                bisection[fn] = {
                    "regressing_pass_index": idx,
                    "regressing_pass_name": pass_names[idx],
                }
                resolved.add(fn)
        regressed -= resolved

    return {
        "baseline_ir": b_ir,
        "candidate_ir": c_ir,
        "baseline_asm": b_asm,
        "candidate_asm": c_asm,
        "bisection": bisection,
    }


# ── Tests ─────────────────────────────────────────────────────────────────

class TestReportStructure:
    def test_file_exists(self):
        assert os.path.exists(REPORT_PATH), "report.json not found"

    def test_valid_json(self, report):
        assert isinstance(report, dict)

    def test_top_level_keys(self, report):
        for key in ("per_function", "bisection", "summary"):
            assert key in report, f"Missing top-level key: {key}"

    def test_per_function_entry_keys(self, report):
        required = [
            "baseline_ir_count", "candidate_ir_count", "ir_delta",
            "status", "baseline_asm_count", "candidate_asm_count", "asm_delta",
        ]
        for func, data in report["per_function"].items():
            for key in required:
                assert key in data, f"{func}: missing key '{key}'"

    def test_summary_keys(self, report):
        required = [
            "total_functions", "num_regressed", "num_improved",
            "num_unchanged", "total_ir_delta", "total_asm_delta",
            "unique_regressing_passes",
        ]
        for key in required:
            assert key in report["summary"], f"Missing summary key: {key}"


class TestFunctionCoverage:
    def test_all_functions_present(self, report, expected):
        for func in expected["baseline_ir"]:
            assert func in report["per_function"], (
                f"Missing function {func} in report"
            )

    def test_no_extra_functions(self, report, expected):
        expected_funcs = set(expected["baseline_ir"]) | set(expected["candidate_ir"])
        for func in report["per_function"]:
            assert func in expected_funcs, (
                f"Unexpected function {func} in report"
            )


class TestIRCounts:
    def test_baseline_ir_counts(self, report, expected):
        for func, exp in expected["baseline_ir"].items():
            actual = report["per_function"][func]["baseline_ir_count"]
            assert actual == exp, (
                f"{func}: baseline_ir_count={actual}, expected={exp}"
            )

    def test_candidate_ir_counts(self, report, expected):
        for func, exp in expected["candidate_ir"].items():
            actual = report["per_function"][func]["candidate_ir_count"]
            assert actual == exp, (
                f"{func}: candidate_ir_count={actual}, expected={exp}"
            )

    def test_ir_delta_correct(self, report):
        for func, data in report["per_function"].items():
            expected_delta = data["candidate_ir_count"] - data["baseline_ir_count"]
            assert data["ir_delta"] == expected_delta, (
                f"{func}: ir_delta={data['ir_delta']}, expected={expected_delta}"
            )

    def test_status_correct(self, report):
        for func, data in report["per_function"].items():
            if data["ir_delta"] > 0:
                expected = "regressed"
            elif data["ir_delta"] < 0:
                expected = "improved"
            else:
                expected = "unchanged"
            assert data["status"] == expected, (
                f"{func}: status='{data['status']}', expected='{expected}'"
            )


class TestASMCounts:
    def test_baseline_asm_counts(self, report, expected):
        for func in report["per_function"]:
            asm_name = func.lstrip("@")
            if asm_name in expected["baseline_asm"]:
                actual = report["per_function"][func]["baseline_asm_count"]
                exp = expected["baseline_asm"][asm_name]
                assert actual == exp, (
                    f"{func}: baseline_asm_count={actual}, expected={exp}"
                )

    def test_candidate_asm_counts(self, report, expected):
        for func in report["per_function"]:
            asm_name = func.lstrip("@")
            if asm_name in expected["candidate_asm"]:
                actual = report["per_function"][func]["candidate_asm_count"]
                exp = expected["candidate_asm"][asm_name]
                assert actual == exp, (
                    f"{func}: candidate_asm_count={actual}, expected={exp}"
                )

    def test_asm_delta_correct(self, report):
        for func, data in report["per_function"].items():
            expected_delta = data["candidate_asm_count"] - data["baseline_asm_count"]
            assert data["asm_delta"] == expected_delta, (
                f"{func}: asm_delta={data['asm_delta']}, expected={expected_delta}"
            )


class TestBisection:
    def test_regressed_functions_have_bisection(self, report):
        for func, data in report["per_function"].items():
            if data["status"] == "regressed":
                assert func in report["bisection"], (
                    f"Regressed function {func} missing from bisection"
                )

    def test_non_regressed_not_in_bisection(self, report):
        for func, data in report["per_function"].items():
            if data["status"] != "regressed":
                assert func not in report["bisection"], (
                    f"Non-regressed function {func} should not be in bisection"
                )

    def test_bisection_pass_index_correct(self, report, expected):
        for func, exp_bisect in expected["bisection"].items():
            assert func in report["bisection"], (
                f"Expected bisection entry for {func}"
            )
            actual = report["bisection"][func]
            assert actual["regressing_pass_index"] == exp_bisect["regressing_pass_index"], (
                f"{func}: pass_index={actual['regressing_pass_index']}, "
                f"expected={exp_bisect['regressing_pass_index']}"
            )

    def test_bisection_pass_name_correct(self, report, expected):
        for func, exp_bisect in expected["bisection"].items():
            actual = report["bisection"][func]
            assert actual["regressing_pass_name"] == exp_bisect["regressing_pass_name"], (
                f"{func}: pass_name='{actual['regressing_pass_name']}', "
                f"expected='{exp_bisect['regressing_pass_name']}'"
            )

    def test_bisection_entry_count(self, report, expected):
        assert len(report["bisection"]) == len(expected["bisection"]), (
            f"bisection entries: {len(report['bisection'])}, "
            f"expected: {len(expected['bisection'])}"
        )


class TestSummary:
    def test_total_functions(self, report):
        assert report["summary"]["total_functions"] == len(report["per_function"])

    def test_status_counts(self, report):
        regressed = sum(
            1 for d in report["per_function"].values() if d["status"] == "regressed"
        )
        improved = sum(
            1 for d in report["per_function"].values() if d["status"] == "improved"
        )
        unchanged = sum(
            1 for d in report["per_function"].values() if d["status"] == "unchanged"
        )
        assert report["summary"]["num_regressed"] == regressed
        assert report["summary"]["num_improved"] == improved
        assert report["summary"]["num_unchanged"] == unchanged

    def test_total_ir_delta(self, report):
        total = sum(d["ir_delta"] for d in report["per_function"].values())
        assert report["summary"]["total_ir_delta"] == total

    def test_total_asm_delta(self, report):
        total = sum(d["asm_delta"] for d in report["per_function"].values())
        assert report["summary"]["total_asm_delta"] == total

    def test_unique_regressing_passes(self, report):
        expected_passes = sorted(set(
            b["regressing_pass_name"] for b in report["bisection"].values()
        ))
        assert sorted(report["summary"]["unique_regressing_passes"]) == expected_passes

    def test_counts_add_up(self, report):
        s = report["summary"]
        assert s["num_regressed"] + s["num_improved"] + s["num_unchanged"] == s["total_functions"]
