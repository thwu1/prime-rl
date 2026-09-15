
"""
Tests for CSV Dialect Detection Adversarial Analysis task.
Verifies score_report.py, challenge CSV files, and results.json.
"""

import csv
import json
import os
import subprocess
import sys
from io import StringIO

import pytest

from clevercsv.detect import Detector, DetectionMethod
from clevercsv.potential_dialects import get_dialects
from clevercsv.read import reader as ccsv_reader

CHALLENGES_DIR = "/app/challenges"
RESULTS_FILE = "/app/results.json"
SCORE_REPORT = "/app/score_report.py"


# ---------- score_report.py tests ----------


class TestScoreReport:
    def test_script_exists(self):
        assert os.path.isfile(SCORE_REPORT), "score_report.py not found"

    def test_produces_valid_json(self):
        fpath = os.path.join(CHALLENGES_DIR, "pipe_consistency.csv")
        if not os.path.isfile(fpath):
            pytest.skip("pipe_consistency.csv not yet created")
        result = subprocess.run(
            [sys.executable, SCORE_REPORT, fpath],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"score_report.py failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        assert "candidates" in data, "Missing 'candidates' key"
        assert "winner" in data, "Missing 'winner' key"
        assert "method" in data, "Missing 'method' key"

    def test_candidate_structure(self):
        fpath = os.path.join(CHALLENGES_DIR, "pipe_consistency.csv")
        if not os.path.isfile(fpath):
            pytest.skip("pipe_consistency.csv not yet created")
        result = subprocess.run(
            [sys.executable, SCORE_REPORT, fpath],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(result.stdout)
        assert len(data["candidates"]) > 0, "No candidates returned"
        for c in data["candidates"]:
            for key in ("delimiter", "quotechar", "escapechar",
                        "pattern_score", "type_score", "consistency_score"):
                assert key in c, f"Candidate missing key '{key}'"
            assert isinstance(c["pattern_score"], (int, float))

    def test_winner_matches_clevercsv(self):
        fpath = os.path.join(CHALLENGES_DIR, "pipe_consistency.csv")
        if not os.path.isfile(fpath):
            pytest.skip("pipe_consistency.csv not yet created")
        result = subprocess.run(
            [sys.executable, SCORE_REPORT, fpath],
            capture_output=True, text=True, timeout=120,
        )
        report = json.loads(result.stdout)
        with open(fpath) as f:
            file_data = f.read()
        dialect = Detector().detect(file_data)
        assert dialect is not None
        assert report["winner"]["delimiter"] == dialect.delimiter
        assert report["winner"]["quotechar"] == dialect.quotechar
        assert report["winner"]["escapechar"] == dialect.escapechar


# ---------- pipe_consistency.csv tests ----------


class TestPipeConsistency:
    @pytest.fixture(autouse=True)
    def load(self):
        self.path = os.path.join(CHALLENGES_DIR, "pipe_consistency.csv")

    def test_file_exists(self):
        assert os.path.isfile(self.path)

    def test_detected_as_pipe_delimited(self):
        with open(self.path) as f:
            data = f.read()
        d = Detector()
        dialect = d.detect(data)
        assert dialect is not None, "Detection returned None"
        assert dialect.delimiter == "|", f"Expected '|', got {dialect.delimiter!r}"
        assert dialect.quotechar == "", f"Expected empty quotechar, got {dialect.quotechar!r}"
        assert dialect.escapechar == "", f"Expected empty escapechar, got {dialect.escapechar!r}"

    def test_uses_consistency_method(self):
        with open(self.path) as f:
            data = f.read()
        d = Detector()
        d.detect(data)
        assert d.method_ == DetectionMethod.CONSISTENCY, (
            f"Expected 'consistency' detection method, got {d.method_!r}"
        )

    def test_minimum_dimensions(self):
        with open(self.path) as f:
            data = f.read()
        d = Detector()
        dialect = d.detect(data)
        assert dialect is not None
        parsed = list(ccsv_reader(StringIO(data), dialect))
        assert len(parsed) >= 9, f"Need >=9 rows (header+8 data), got {len(parsed)}"
        for i, row in enumerate(parsed):
            assert len(row) >= 4, f"Row {i} has {len(row)} cols, need >=4"


# ---------- mixed_quoting.csv tests ----------


class TestMixedQuoting:
    @pytest.fixture(autouse=True)
    def load(self):
        self.path = os.path.join(CHALLENGES_DIR, "mixed_quoting.csv")

    def test_file_exists(self):
        assert os.path.isfile(self.path)

    def test_detected_dialect(self):
        with open(self.path) as f:
            data = f.read()
        dialect = Detector().detect(data)
        assert dialect is not None
        assert dialect.delimiter == ";", f"Expected ';', got {dialect.delimiter!r}"
        assert dialect.quotechar == "'", f"Expected \"'\", got {dialect.quotechar!r}"

    def test_mixed_quoting_rows(self):
        """At least 4 rows must have both quoted and unquoted cells."""
        with open(self.path) as f:
            lines = [l.strip() for l in f if l.strip()]
        mixed = 0
        for line in lines:
            cells = line.split(";")
            has_q = any(
                c.strip().startswith("'") and c.strip().endswith("'") and len(c.strip()) >= 2
                for c in cells
            )
            has_uq = any(
                not (c.strip().startswith("'") and c.strip().endswith("'") and len(c.strip()) >= 2)
                for c in cells
            )
            if has_q and has_uq:
                mixed += 1
        assert mixed >= 4, f"Need >=4 mixed-quoting rows, got {mixed}"

    def test_minimum_dimensions(self):
        with open(self.path) as f:
            data = f.read()
        dialect = Detector().detect(data)
        assert dialect is not None
        parsed = list(ccsv_reader(StringIO(data), dialect))
        assert len(parsed) >= 7, f"Need >=7 rows (header+6), got {len(parsed)}"
        for i, row in enumerate(parsed):
            assert len(row) >= 5, f"Row {i} has {len(row)} cols, need >=5"


# ---------- sniffer_disagree.csv tests ----------


class TestSnifferDisagree:
    @pytest.fixture(autouse=True)
    def load(self):
        self.path = os.path.join(CHALLENGES_DIR, "sniffer_disagree.csv")

    def test_file_exists(self):
        assert os.path.isfile(self.path)

    def test_delimiters_differ(self):
        with open(self.path) as f:
            data = f.read()
        clever = Detector().detect(data)
        assert clever is not None, "CleverCSV detection returned None"

        sniffer = csv.Sniffer()
        sniffed = sniffer.sniff(data)
        assert sniffed.delimiter != clever.delimiter, (
            f"Sniffer and CleverCSV both picked {clever.delimiter!r} — "
            "need them to disagree"
        )

    def test_minimum_rows(self):
        with open(self.path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) >= 6, f"Need >=6 data rows, got {len(lines)}"


# ---------- many_candidates.csv tests ----------


class TestManyCandidates:
    @pytest.fixture(autouse=True)
    def load(self):
        self.path = os.path.join(CHALLENGES_DIR, "many_candidates.csv")

    def test_file_exists(self):
        assert os.path.isfile(self.path)

    def test_at_least_20_candidates(self):
        with open(self.path) as f:
            data = f.read()
        dialects = get_dialects(data)
        assert len(dialects) >= 20, f"Need >=20 candidates, got {len(dialects)}"

    def test_minimum_dimensions(self):
        with open(self.path) as f:
            data = f.read()
        dialect = Detector().detect(data)
        assert dialect is not None, "Detection returned None for many_candidates.csv"
        parsed = list(ccsv_reader(StringIO(data), dialect))
        assert len(parsed) >= 5, f"Need >=5 rows, got {len(parsed)}"
        for i, row in enumerate(parsed):
            assert len(row) >= 3, f"Row {i} has {len(row)} cols, need >=3"


# ---------- results.json tests ----------


class TestResults:
    def test_file_exists(self):
        assert os.path.isfile(RESULTS_FILE), "results.json not found"

    def test_valid_json(self):
        with open(RESULTS_FILE) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_all_challenges_present(self):
        with open(RESULTS_FILE) as f:
            data = json.load(f)
        expected = {
            "pipe_consistency.csv",
            "mixed_quoting.csv",
            "sniffer_disagree.csv",
            "many_candidates.csv",
        }
        assert expected.issubset(set(data.keys())), (
            f"Missing keys: {expected - set(data.keys())}"
        )

    def test_each_entry_has_structure(self):
        with open(RESULTS_FILE) as f:
            data = json.load(f)
        for name, entry in data.items():
            assert "candidates" in entry, f"'{name}' missing 'candidates'"
            assert "winner" in entry, f"'{name}' missing 'winner'"
            assert "method" in entry, f"'{name}' missing 'method'"
