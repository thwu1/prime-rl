
import pytest
import json
import os
import subprocess
import shutil


# ── Expected corrupted entries ──────────────────────────────────────────────

EXPECTED_ERRORS = {
    24: {"language": "turahi",  "number": 80,   "wrong_word": "ram dun fi",               "correct_word": "ram fi dun"},
    28: {"language": "turahi",  "number": 200,  "wrong_word": "so ram na",                 "correct_word": "so ram dun"},
    33: {"language": "turahi",  "number": 500,  "wrong_word": "po ram mu dun ke",          "correct_word": "po ram la dun ke"},
    56: {"language": "belago",  "number": 33,   "wrong_word": "kal tum doi",               "correct_word": "kal tum tin"},
    65: {"language": "belago",  "number": 120,  "wrong_word": "nen doi kal",               "correct_word": "nen cha kal"},
    72: {"language": "belago",  "number": 800,  "wrong_word": "tin bor",                   "correct_word": "doi bor"},
    98: {"language": "renshi",  "number": 72,   "wrong_word": "hes zan ek",                "correct_word": "hes zan"},
    115: {"language": "renshi", "number": 1000, "wrong_word": "hes gros feek zan pen",     "correct_word": "hes gros feek zan kat"},
}

# ── Expected decode results: (system, word_form) -> decimal ────────────────

DECODE_EXPECTED = {
    ("turahi", "dun fi"): 10,
    ("turahi", "fi dun so"): 19,
    ("turahi", "ke dun fi"): 34,
    ("turahi", "la dun so"): 51,
    ("turahi", "fi ram la"): 134,
    ("turahi", "so ram dun po"): 207,
    ("turahi", "ke ram so dun fi"): 282,
    ("turahi", "mu ram po dun so"): 379,
    ("turahi", "la ram ke dun mu"): 421,
    ("turahi", "vol mu dun ke"): 556,
    ("turahi", "vol so ram fi dun na"): 721,
    ("turahi", "fi vol ke ram so dun po"): 1311,
    ("belago", "tum doi"): 12,
    ("belago", "nen tin kal"): 160,
    ("belago", "tin kal nen doi"): 67,
    ("belago", "nen pak kal tum tin"): 193,
    ("belago", "tum cha kal nen pak"): 229,
    ("belago", "tum nen tin kal nen"): 365,
    ("belago", "bor doi kal tin"): 443,
    ("belago", "bor tum nen pak kal tum nen pak"): 799,
    ("belago", "tin bor nen kal tum doi"): 1312,
    ("belago", "pak bor tum nen doi kal nen pak"): 1949,
    ("belago", "nen bor kal tum nen pak"): 2039,
    ("belago", "tum bor tum nen pak kal tum doi"): 4392,
    ("renshi", "zan dwa"): 14,
    ("renshi", "zan sep"): 19,
    ("renshi", "zan fedwa"): 22,
    ("renshi", "tri zan pen"): 41,
    ("renshi", "pen zan dwa"): 62,
    ("renshi", "sep zan fetri"): 93,
    ("renshi", "feek zan sep"): 139,
    ("renshi", "gros tri"): 147,
    ("renshi", "gros hes zan pen"): 221,
    ("renshi", "dwa gros sep zan fetri"): 381,
    ("renshi", "kat gros fekat zan tri"): 675,
    ("renshi", "sep gros feek zan feek"): 1151,
}

# ── Expected encode results: (system, number) -> word_form ─────────────────

ENCODE_EXPECTED = {
    ("turahi", 13): "dun mu",
    ("turahi", 27): "so dun so",
    ("turahi", 45): "mu dun mu",
    ("turahi", 99): "ram ke dun so",
    ("turahi", 150): "fi ram fi dun la",
    ("turahi", 250): "so ram po dun fi",
    ("turahi", 333): "mu ram dun mu",
    ("turahi", 400): "la ram fi dun",
    ("turahi", 511): "po ram po dun po",
    ("turahi", 1000): "vol po ram mu dun",
    ("belago", 14): "tum pak",
    ("belago", 37): "kal tum nen doi",
    ("belago", 76): "tin kal tum nen cha",
    ("belago", 123): "nen cha kal tin",
    ("belago", 256): "tum doi kal tum nen cha",
    ("belago", 350): "tum nen doi kal tum",
    ("belago", 444): "bor doi kal pak",
    ("belago", 750): "bor tum nen doi kal tum",
    ("belago", 1500): "tin bor tum nen kal",
    ("belago", 5555): "tum tin bor tum nen doi kal tum nen",
    ("renshi", 16): "zan kat",
    ("renshi", 35): "dwa zan feek",
    ("renshi", 50): "kat zan dwa",
    ("renshi", 77): "hes zan pen",
    ("renshi", 111): "fetri zan tri",
    ("renshi", 130): "fedwa zan fedwa",
    ("renshi", 201): "gros kat zan fetri",
    ("renshi", 333): "dwa gros tri zan fetri",
    ("renshi", 501): "tri gros pen zan fetri",
    ("renshi", 999): "hes gros feek zan tri",
}

# ── Expected cross-system results ──────────────────────────────────────────

CROSS_EXPECTED = {
    ("turahi", "la ram ke dun", "belago"): "bor tum nen cha",
    ("belago", "tin kal nen tin", "renshi"): "pen zan fekat",
    ("renshi", "dwa gros kat zan", "turahi"): "mu ram fi dun",
    ("turahi", "vol fi ram so dun la", "belago"): "bor tum tin kal tum",
    ("renshi", "pen gros sep zan pen", "belago"): "doi bor nen pak",
}


def _read_tsv(path, min_cols):
    """Read a TSV file, skip comments/blanks, return list of row-tuples."""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= min_cols:
                rows.append(tuple(p.strip() for p in parts))
    return rows


# ── Error detection tests ──────────────────────────────────────────────────

class TestErrorDetection:
    @pytest.fixture(autouse=True)
    def load_errors(self):
        path = "/app/output/errors.json"
        assert os.path.exists(path), f"Missing output file: {path}"
        with open(path) as f:
            self.errors = json.load(f)
        self.error_map = {e["id"]: e for e in self.errors}

    def test_error_count(self):
        assert len(self.errors) == 8, (
            f"Expected 8 corrupted entries, found {len(self.errors)}"
        )

    def test_error_ids(self):
        found_ids = set(self.error_map.keys())
        expected_ids = set(EXPECTED_ERRORS.keys())
        assert found_ids == expected_ids, (
            f"Wrong error IDs. Expected {sorted(expected_ids)}, got {sorted(found_ids)}"
        )

    @pytest.mark.parametrize("row_id,expected", list(EXPECTED_ERRORS.items()),
                             ids=[f"id{k}" for k in EXPECTED_ERRORS])
    def test_error_detail(self, row_id, expected):
        assert row_id in self.error_map, f"Missing error for ID {row_id}"
        e = self.error_map[row_id]
        assert e["language"] == expected["language"], (
            f"ID {row_id}: expected language '{expected['language']}', got '{e['language']}'"
        )
        assert e["number"] == expected["number"], (
            f"ID {row_id}: expected number {expected['number']}, got {e['number']}"
        )
        assert e["wrong_word"] == expected["wrong_word"], (
            f"ID {row_id}: expected wrong_word '{expected['wrong_word']}', got '{e['wrong_word']}'"
        )
        assert e["correct_word"] == expected["correct_word"], (
            f"ID {row_id}: expected correct_word '{expected['correct_word']}', got '{e['correct_word']}'"
        )


# ── Fix SQL tests ──────────────────────────────────────────────────────────

class TestFixSQL:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        self.db_copy = str(tmp_path / "test_fieldwork.db")
        shutil.copy("/data/fieldwork.db", self.db_copy)
        fix_path = "/app/output/fix.sql"
        assert os.path.exists(fix_path), f"Missing output file: {fix_path}"
        with open(fix_path) as f:
            self.fix_sql = f.read()
        result = subprocess.run(
            ["sqlite3", self.db_copy],
            input=self.fix_sql,
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"fix.sql failed to execute: {result.stderr}"
        )

    @pytest.mark.parametrize("row_id,expected", list(EXPECTED_ERRORS.items()),
                             ids=[f"fix_id{k}" for k in EXPECTED_ERRORS])
    def test_fix_corrects_entry(self, row_id, expected):
        result = subprocess.run(
            ["sqlite3", self.db_copy,
             f"SELECT word_form FROM training WHERE id={row_id}"],
            capture_output=True, text=True
        )
        actual = result.stdout.strip()
        assert actual == expected["correct_word"], (
            f"After fix, row {row_id}: expected '{expected['correct_word']}', got '{actual}'"
        )

    def test_fix_preserves_correct_entries(self):
        """Verify that non-corrupted entries are not modified."""
        checks = [(1, "na"), (37, "cha"), (76, "ek"), (21, "ram"), (52, "kal"), (87, "zan")]
        for row_id, expected_word in checks:
            result = subprocess.run(
                ["sqlite3", self.db_copy,
                 f"SELECT word_form FROM training WHERE id={row_id}"],
                capture_output=True, text=True
            )
            actual = result.stdout.strip()
            assert actual == expected_word, (
                f"Non-corrupted row {row_id} was modified: expected '{expected_word}', got '{actual}'"
            )


# ── Decode tests ───────────────────────────────────────────────────────────

class TestDecode:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/output/decode_results.tsv"
        assert os.path.exists(path), f"Missing output file: {path}"
        self.results = {}
        for row in _read_tsv(path, 3):
            system, word, number = row[0], row[1], row[2]
            self.results[(system, word)] = int(number)

    @pytest.mark.parametrize("key,expected", list(DECODE_EXPECTED.items()),
                             ids=[f"{s}:{w}" for (s, w) in DECODE_EXPECTED])
    def test_decode(self, key, expected):
        assert key in self.results, f"Missing decode entry for {key}"
        assert self.results[key] == expected, (
            f"Decode {key}: expected {expected}, got {self.results[key]}"
        )


# ── Encode tests ───────────────────────────────────────────────────────────

class TestEncode:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/output/encode_results.tsv"
        assert os.path.exists(path), f"Missing output file: {path}"
        self.results = {}
        for row in _read_tsv(path, 3):
            system, number, word = row[0], row[1], row[2]
            self.results[(system, int(number))] = word

    @pytest.mark.parametrize("key,expected", list(ENCODE_EXPECTED.items()),
                             ids=[f"{s}:{n}" for (s, n) in ENCODE_EXPECTED])
    def test_encode(self, key, expected):
        assert key in self.results, f"Missing encode entry for {key}"
        assert self.results[key] == expected, (
            f"Encode {key}: expected '{expected}', got '{self.results[key]}'"
        )


# ── Cross-system tests ────────────────────────────────────────────────────

class TestCrossSystem:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/output/cross_results.tsv"
        assert os.path.exists(path), f"Missing output file: {path}"
        self.results = {}
        for row in _read_tsv(path, 4):
            src_sys, src_word, tgt_sys, tgt_word = row[0], row[1], row[2], row[3]
            self.results[(src_sys, src_word, tgt_sys)] = tgt_word

    @pytest.mark.parametrize("key,expected", list(CROSS_EXPECTED.items()),
                             ids=[f"{ss}:{sw}->{ts}" for (ss, sw, ts) in CROSS_EXPECTED])
    def test_cross(self, key, expected):
        assert key in self.results, f"Missing cross-system entry for {key}"
        assert self.results[key] == expected, (
            f"Cross {key}: expected '{expected}', got '{self.results[key]}'"
        )
