
import json
import os
import configparser
import sqlite3
import tempfile
import pytest

APP_DIR = "/app"
COVERAGERC = os.path.join(APP_DIR, ".coveragerc")
COVERAGE_DB = os.path.join(APP_DIR, ".coverage")
REPORT = os.path.join(APP_DIR, "impact_report.json")
CHANGES = os.path.join(APP_DIR, "changes.json")


def normalize_path(p):
    """Normalize to calclib/... relative format."""
    p = os.path.normpath(p).replace("\\", "/")
    parts = p.split("/")
    for i, part in enumerate(parts):
        if part == "calclib":
            return "/".join(parts[i:])
    return p


class TestCoverageConfig:
    """Verify .coveragerc bugs are fixed."""

    def test_coveragerc_exists(self):
        assert os.path.isfile(COVERAGERC), ".coveragerc not found"

    def test_branch_in_run_section(self):
        config = configparser.ConfigParser()
        config.read(COVERAGERC)
        assert config.has_option("run", "branch"), "branch not in [run] section"
        assert config.getboolean("run", "branch"), "branch is not True in [run]"

    def test_dynamic_context(self):
        config = configparser.ConfigParser()
        config.read(COVERAGERC)
        assert config.has_option("run", "dynamic_context"), "dynamic_context missing from [run]"
        assert config.get("run", "dynamic_context").strip() == "test_function"

    def test_concurrency_multiprocessing(self):
        config = configparser.ConfigParser()
        config.read(COVERAGERC)
        assert config.has_option("run", "concurrency"), "concurrency missing from [run]"
        assert "multiprocessing" in config.get("run", "concurrency")

    def test_source_path_valid(self):
        config = configparser.ConfigParser()
        config.read(COVERAGERC)
        if config.has_option("run", "source"):
            source = config.get("run", "source").strip()
            assert "/opt/" not in source, "Source still points to /opt/ (wrong path)"

    def test_omit_does_not_exclude_batch(self):
        config = configparser.ConfigParser()
        config.read(COVERAGERC)
        if config.has_option("run", "omit"):
            omit = config.get("run", "omit").lower()
            assert "batch" not in omit, "Omit pattern still excludes batch.py"

    def test_exclude_lines_not_raises(self):
        config = configparser.ConfigParser()
        config.read(COVERAGERC)
        if config.has_option("report", "exclude_lines"):
            excludes = config.get("report", "exclude_lines")
            assert "raise ValueError" not in excludes, "exclude_lines masks raise ValueError"
            assert "raise TypeError" not in excludes, "exclude_lines masks raise TypeError"


class TestCoverageOutcome:
    """Verify coverage was collected correctly."""

    def test_coverage_db_exists(self):
        assert os.path.isfile(COVERAGE_DB), ".coverage database not found"

    def test_is_valid_sqlite(self):
        conn = sqlite3.connect(COVERAGE_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "file" in tables, "Not a valid coverage.py database"

    def test_has_arc_data(self):
        from coverage.sqldata import CoverageData
        data = CoverageData(COVERAGE_DB)
        data.read()
        assert data.has_arcs(), "No arc data — branch coverage was not enabled"

    def test_has_context_data(self):
        from coverage.sqldata import CoverageData
        data = CoverageData(COVERAGE_DB)
        data.read()
        contexts = data.measured_contexts()
        non_empty = {c for c in contexts if c}
        assert len(non_empty) >= 5, f"Expected >= 5 test contexts, got {len(non_empty)}"

    def test_all_modules_covered(self):
        from coverage.sqldata import CoverageData
        data = CoverageData(COVERAGE_DB)
        data.read()
        files = data.measured_files()
        basenames = {os.path.basename(f) for f in files}
        assert "core.py" in basenames, "core.py not measured"
        assert "stats.py" in basenames, "stats.py not measured"
        assert "batch.py" in basenames, "batch.py not measured"

    def test_batch_has_coverage(self):
        from coverage.sqldata import CoverageData
        data = CoverageData(COVERAGE_DB)
        data.read()
        batch_files = [f for f in data.measured_files() if "batch" in os.path.basename(f)]
        assert batch_files, "batch.py not in measured files"
        for bf in batch_files:
            lines = data.lines(bf)
            assert lines and len(lines) > 5, f"batch.py has too few covered lines: {len(lines) if lines else 0}"


class TestImpactReport:
    """Verify the impact report is correct."""

    @pytest.fixture
    def report(self):
        assert os.path.isfile(REPORT), "impact_report.json not found"
        with open(REPORT) as f:
            return json.load(f)

    @pytest.fixture
    def cov_data(self):
        from coverage.sqldata import CoverageData
        data = CoverageData(COVERAGE_DB)
        data.read()
        return data

    def test_report_structure(self, report):
        assert "coverage_summary" in report, "Missing coverage_summary"
        assert "context_mapping" in report, "Missing context_mapping"
        assert "exclusive_coverage" in report, "Missing exclusive_coverage"
        assert "affected_tests" in report, "Missing affected_tests"

    def test_coverage_summary_has_all_modules(self, report):
        summary = report["coverage_summary"]
        basenames = {os.path.basename(f) for f in summary}
        assert "core.py" in basenames, "core.py missing from coverage_summary"
        assert "stats.py" in basenames, "stats.py missing from coverage_summary"
        assert "batch.py" in basenames, "batch.py missing from coverage_summary"

    def test_coverage_summary_only_calclib(self, report):
        for fname in report["coverage_summary"]:
            norm = normalize_path(fname)
            assert norm.startswith("calclib/"), f"Unexpected file in summary: {fname}"

    def test_coverage_summary_fields(self, report):
        for fname, stats in report["coverage_summary"].items():
            assert "lines_covered" in stats, f"{fname}: missing lines_covered"
            assert "lines_total" in stats, f"{fname}: missing lines_total"
            assert "branches_covered" in stats, f"{fname}: missing branches_covered"
            assert "branches_total" in stats, f"{fname}: missing branches_total"
            assert stats["lines_covered"] <= stats["lines_total"], f"{fname}: lines_covered > lines_total"
            assert stats["branches_covered"] <= stats["branches_total"], f"{fname}: branches_covered > branches_total"
            # Skip empty files like __init__.py
            if stats["lines_total"] > 0:
                assert stats["lines_covered"] > 0, f"{fname}: has statements but none covered"

    def test_coverage_summary_accuracy(self, report):
        """Cross-check coverage numbers against coverage.py's own analysis."""
        import coverage as cov_module
        cov = cov_module.Coverage()
        cov.load()

        tmpfile = tempfile.mktemp(suffix=".json")
        cov.json_report(outfile=tmpfile)
        with open(tmpfile) as f:
            ref = json.load(f)
        os.unlink(tmpfile)

        for fname, stats in report["coverage_summary"].items():
            norm = normalize_path(fname)
            ref_file = None
            for rf in ref["files"]:
                if normalize_path(rf) == norm:
                    ref_file = rf
                    break
            assert ref_file is not None, f"File {fname} (normalized: {norm}) not in reference report"
            ref_stats = ref["files"][ref_file]["summary"]
            assert stats["lines_covered"] == ref_stats["covered_lines"], \
                f"{fname}: lines_covered {stats['lines_covered']} != {ref_stats['covered_lines']}"
            assert stats["lines_total"] == ref_stats["num_statements"], \
                f"{fname}: lines_total {stats['lines_total']} != {ref_stats['num_statements']}"
            assert stats["branches_covered"] == ref_stats["covered_branches"], \
                f"{fname}: branches_covered {stats['branches_covered']} != {ref_stats['covered_branches']}"
            assert stats["branches_total"] == ref_stats["num_branches"], \
                f"{fname}: branches_total {stats['branches_total']} != {ref_stats['num_branches']}"

    def test_context_mapping_nonempty(self, report):
        cm = report["context_mapping"]
        assert len(cm) > 0, "Empty context_mapping"
        for ctx, files in cm.items():
            assert len(files) > 0, f"Context {ctx} maps to no files"

    def test_context_mapping_accuracy(self, report, cov_data):
        """Cross-reference context mapping with database."""
        cm = report["context_mapping"]

        ref_cm = {}
        for fname in cov_data.measured_files():
            rel = normalize_path(fname)
            if not rel.startswith("calclib/"):
                continue
            ctx_by_line = cov_data.contexts_by_lineno(fname)
            for line, contexts in ctx_by_line.items():
                for ctx in contexts:
                    if ctx:
                        ref_cm.setdefault(ctx, set()).add(rel)

        for ctx in cm:
            assert ctx in ref_cm, f"Context {ctx} not found in DB"
            report_files = {normalize_path(f) for f in cm[ctx]}
            assert report_files == ref_cm[ctx], \
                f"Files mismatch for context {ctx}: report={report_files}, db={ref_cm[ctx]}"

        for ctx in ref_cm:
            assert ctx in cm, f"Context {ctx} in DB but missing from report"

    def test_exclusive_coverage_correctness(self, report, cov_data):
        """Verify each exclusive line is truly covered by exactly one context."""
        ec = report["exclusive_coverage"]

        line_ctx_map = {}
        for fname in cov_data.measured_files():
            rel = normalize_path(fname)
            if not rel.startswith("calclib/"):
                continue
            ctx_by_line = cov_data.contexts_by_lineno(fname)
            for line, contexts in ctx_by_line.items():
                non_empty = {c for c in contexts if c}
                if non_empty:
                    line_ctx_map[(rel, line)] = non_empty

        for ctx, file_lines in ec.items():
            for fname, lines in file_lines.items():
                norm = normalize_path(fname)
                for line in lines:
                    key = (norm, line)
                    assert key in line_ctx_map, \
                        f"Line {line} in {norm} not found in coverage data"
                    covering = line_ctx_map[key]
                    assert len(covering) == 1, \
                        f"Line {line} in {norm} covered by {len(covering)} contexts, not exclusive: {covering}"
                    assert ctx in covering, \
                        f"Line {line} in {norm} covered by {covering}, not by claimed {ctx}"

    def test_exclusive_coverage_complete(self, report, cov_data):
        """Verify all exclusive lines are reported (no omissions)."""
        ec = report["exclusive_coverage"]

        reported_exclusive = set()
        for ctx, file_lines in ec.items():
            for fname, lines in file_lines.items():
                for line in lines:
                    reported_exclusive.add((normalize_path(fname), line, ctx))

        for fname in cov_data.measured_files():
            rel = normalize_path(fname)
            if not rel.startswith("calclib/"):
                continue
            ctx_by_line = cov_data.contexts_by_lineno(fname)
            for line, contexts in ctx_by_line.items():
                non_empty = {c for c in contexts if c}
                if len(non_empty) == 1:
                    ctx = next(iter(non_empty))
                    assert (rel, line, ctx) in reported_exclusive, \
                        f"Exclusive line {line} in {rel} by {ctx} not in report"

    def test_affected_tests(self, report, cov_data):
        """Verify affected tests match changes.json against DB."""
        with open(CHANGES) as f:
            changes = json.load(f)

        expected_affected = set()
        for change in changes["changes"]:
            target_file = change["file"]
            target_lines = set(change["lines"])
            for db_fname in cov_data.measured_files():
                rel = normalize_path(db_fname)
                if rel == target_file:
                    ctx_by_line = cov_data.contexts_by_lineno(db_fname)
                    for line in target_lines:
                        if line in ctx_by_line:
                            for ctx in ctx_by_line[line]:
                                if ctx:
                                    expected_affected.add(ctx)
                    break

        report_affected = set(report["affected_tests"])
        assert report_affected == expected_affected, \
            f"Affected tests mismatch.\nExpected: {sorted(expected_affected)}\nGot: {sorted(report_affected)}"
