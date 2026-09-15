"""Tests for BitTorrent forensic reconstruction task."""

import hashlib
import json
import os
import random

import pytest

SEED = 20240801
PIECE_LENGTH = 2048
OUTPUT_DIR = "/app/output"
REPORT_PATH = os.path.join(OUTPUT_DIR, "report.json")
FILES_DIR = os.path.join(OUTPUT_DIR, "files", "dataset")

FILE_SPECS = [
    ("src/main.c", 2500),
    ("src/util.h", 800),
    ("src/parser/lexer.c", 3200),
    ("src/parser/tokens.dat", 450),
    ("docs/README.txt", 1800),
    ("docs/api_reference.md", 4100),
    ("build/Makefile", 600),
    ("build/config.ini", 280),
    ("assets/icon.bin", 1500),
    ("assets/font.dat", 2200),
]


def bencode_encode(obj):
    if isinstance(obj, int):
        return "i{}e".format(obj).encode("ascii")
    elif isinstance(obj, bytes):
        return str(len(obj)).encode("ascii") + b":" + obj
    elif isinstance(obj, list):
        return b"l" + b"".join(bencode_encode(item) for item in obj) + b"e"
    elif isinstance(obj, dict):
        result = b"d"
        for key, value in sorted(obj.items(), key=lambda x: x[0]):
            assert isinstance(key, bytes)
            result += bencode_encode(key) + bencode_encode(value)
        result += b"e"
        return result
    raise TypeError("Cannot bencode {}".format(type(obj)))


class ExpectedData:
    def __init__(self):
        rng = random.Random(SEED)

        self.file_contents = {}
        for path, size in FILE_SPECS:
            if path.endswith(".bin") or path.endswith(".dat"):
                content = bytes([rng.randint(0, 255) for _ in range(size)])
            else:
                content = bytes([rng.randint(32, 126) for _ in range(size)])
            self.file_contents[path] = content

        self.concat = b"".join(self.file_contents[p] for p, _ in FILE_SPECS)
        self.total_size = len(self.concat)

        self.pieces = []
        piece_hashes_raw = b""
        self.piece_hashes_hex = []
        for i in range(0, self.total_size, PIECE_LENGTH):
            piece = self.concat[i:i + PIECE_LENGTH]
            self.pieces.append(piece)
            h = hashlib.sha1(piece)
            piece_hashes_raw += h.digest()
            self.piece_hashes_hex.append(h.hexdigest())

        self.num_pieces = len(self.pieces)

        files_list = []
        for path, _ in FILE_SPECS:
            parts = path.split("/")
            files_list.append({
                b"length": len(self.file_contents[path]),
                b"path": [p.encode() for p in parts],
            })

        info_dict = {
            b"files": files_list,
            b"name": b"dataset",
            b"piece length": PIECE_LENGTH,
            b"pieces": piece_hashes_raw,
        }
        self.info_hash = hashlib.sha1(bencode_encode(info_dict)).hexdigest()

        self.file_ranges = {}
        offset = 0
        for path, size in FILE_SPECS:
            self.file_ranges[path] = (offset, offset + size)
            offset += size


_expected = None


def get_expected():
    global _expected
    if _expected is None:
        _expected = ExpectedData()
    return _expected


_report = None


def get_report():
    global _report
    if _report is None:
        with open(REPORT_PATH) as f:
            _report = json.load(f)
    return _report


PIECE_STATUS_MAP = {
    0: "valid",
    1: "corrupted",
    2: "valid",
    3: "valid",
    4: "missing",
    5: "valid",
    6: "valid",
    7: "valid",
    8: "valid",
}

VERIFIED_INDICES = {0, 2, 3, 5, 6, 7, 8}


class TestReportExists:
    def test_report_file_exists(self):
        assert os.path.exists(REPORT_PATH), \
            "report.json not found at {}".format(REPORT_PATH)

    def test_report_is_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_top_level_fields(self):
        report = get_report()
        for field in [
            "info_hash", "piece_length", "total_pieces",
            "total_size", "pieces", "files",
        ]:
            assert field in report, "Missing field: {}".format(field)


class TestReportMetadata:
    def test_piece_length(self):
        assert get_report()["piece_length"] == PIECE_LENGTH

    def test_total_pieces(self):
        assert get_report()["total_pieces"] == get_expected().num_pieces

    def test_total_size(self):
        assert get_report()["total_size"] == get_expected().total_size

    def test_info_hash(self):
        report_hash = get_report()["info_hash"].lower()
        expected_hash = get_expected().info_hash.lower()
        assert report_hash == expected_hash, \
            "info_hash mismatch: got {} expected {}".format(
                report_hash, expected_hash)


class TestPieceStatuses:
    def test_piece_count_in_report(self):
        assert len(get_report()["pieces"]) == get_expected().num_pieces

    @pytest.mark.parametrize("idx", range(9))
    def test_piece_status(self, idx):
        pieces = get_report()["pieces"]
        p = next((p for p in pieces if p["index"] == idx), None)
        assert p is not None, "Piece {} not in report".format(idx)
        assert p["status"] == PIECE_STATUS_MAP[idx], \
            "Piece {} status: got {} expected {}".format(
                idx, p["status"], PIECE_STATUS_MAP[idx])

    @pytest.mark.parametrize("idx", sorted(VERIFIED_INDICES))
    def test_valid_piece_hash(self, idx):
        pieces = get_report()["pieces"]
        p = next(p for p in pieces if p["index"] == idx)
        expected_hash = get_expected().piece_hashes_hex[idx]
        assert "hash" in p, "Valid piece {} must include 'hash'".format(idx)
        assert p["hash"].lower() == expected_hash.lower()

    def test_corrupted_piece_has_both_hashes(self):
        pieces = get_report()["pieces"]
        p1 = next(p for p in pieces if p["index"] == 1)
        assert "expected_hash" in p1
        assert "actual_hash" in p1
        expected = get_expected().piece_hashes_hex[1]
        assert p1["expected_hash"].lower() == expected.lower()
        assert p1["actual_hash"].lower() != expected.lower()

    def test_duplicate_piece_count(self):
        pieces = get_report()["pieces"]
        p6 = next(p for p in pieces if p["index"] == 6)
        assert p6.get("duplicates_found", 0) == 2, \
            "Piece 6 should report duplicates_found=2"

    def test_pieces_sorted_by_index(self):
        pieces = get_report()["pieces"]
        indices = [p["index"] for p in pieces]
        assert indices == sorted(indices)


class TestFileStatuses:
    def test_file_count(self):
        assert len(get_report()["files"]) == len(FILE_SPECS)

    def _get_file_entry(self, path):
        return next(f for f in get_report()["files"] if f["path"] == path)

    def test_main_c_partial(self):
        f = self._get_file_entry("src/main.c")
        assert f["status"] == "partial"
        assert f["length"] == 2500

    def test_util_h_partial(self):
        f = self._get_file_entry("src/util.h")
        assert f["status"] == "partial"
        assert f["length"] == 800

    def test_lexer_c_partial(self):
        f = self._get_file_entry("src/parser/lexer.c")
        assert f["status"] == "partial"
        assert f["length"] == 3200

    def test_tokens_dat_complete(self):
        f = self._get_file_entry("src/parser/tokens.dat")
        assert f["status"] == "complete"
        assert f["length"] == 450

    def test_readme_partial(self):
        f = self._get_file_entry("docs/README.txt")
        assert f["status"] == "partial"
        assert f["length"] == 1800

    def test_api_reference_partial(self):
        f = self._get_file_entry("docs/api_reference.md")
        assert f["status"] == "partial"
        assert f["length"] == 4100

    def test_makefile_complete(self):
        f = self._get_file_entry("build/Makefile")
        assert f["status"] == "complete"
        assert f["length"] == 600

    def test_config_ini_complete(self):
        f = self._get_file_entry("build/config.ini")
        assert f["status"] == "complete"
        assert f["length"] == 280

    def test_icon_bin_complete(self):
        f = self._get_file_entry("assets/icon.bin")
        assert f["status"] == "complete"
        assert f["length"] == 1500

    def test_font_dat_complete(self):
        f = self._get_file_entry("assets/font.dat")
        assert f["status"] == "complete"
        assert f["length"] == 2200


class TestReconstructedFilesExist:
    def test_output_directory(self):
        assert os.path.isdir(FILES_DIR), \
            "Output dir {} not found".format(FILES_DIR)

    @pytest.mark.parametrize("path", [p for p, _ in FILE_SPECS])
    def test_file_present(self, path):
        full = os.path.join(FILES_DIR, path)
        assert os.path.exists(full), "Missing: {}".format(full)

    @pytest.mark.parametrize("path,size", FILE_SPECS)
    def test_file_size(self, path, size):
        full = os.path.join(FILES_DIR, path)
        actual = os.path.getsize(full)
        assert actual == size, \
            "{}: expected {} bytes, got {}".format(path, size, actual)


class TestCompleteFiles:
    """Files fully covered by valid pieces match original content."""

    def test_tokens_dat(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "src/parser/tokens.dat"), "rb") as f:
            actual = f.read()
        assert actual == exp.file_contents["src/parser/tokens.dat"]

    def test_makefile(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "build/Makefile"), "rb") as f:
            actual = f.read()
        assert actual == exp.file_contents["build/Makefile"]

    def test_config_ini(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "build/config.ini"), "rb") as f:
            actual = f.read()
        assert actual == exp.file_contents["build/config.ini"]

    def test_icon_bin(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "assets/icon.bin"), "rb") as f:
            actual = f.read()
        assert actual == exp.file_contents["assets/icon.bin"]

    def test_font_dat(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "assets/font.dat"), "rb") as f:
            actual = f.read()
        assert actual == exp.file_contents["assets/font.dat"]


class TestPartialFiles:
    """Partial files: valid regions match original, bad regions are zeros."""

    def test_main_c_valid_region(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "src/main.c"), "rb") as f:
            actual = f.read()
        assert actual[:2048] == exp.file_contents["src/main.c"][:2048]

    def test_main_c_zeroed_region(self):
        with open(os.path.join(FILES_DIR, "src/main.c"), "rb") as f:
            actual = f.read()
        assert actual[2048:] == b"\x00" * (2500 - 2048)

    def test_util_h_entirely_zeroed(self):
        with open(os.path.join(FILES_DIR, "src/util.h"), "rb") as f:
            actual = f.read()
        assert actual == b"\x00" * 800

    def test_lexer_c_zeroed_start(self):
        with open(os.path.join(FILES_DIR, "src/parser/lexer.c"), "rb") as f:
            actual = f.read()
        assert actual[:796] == b"\x00" * 796

    def test_lexer_c_valid_rest(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "src/parser/lexer.c"), "rb") as f:
            actual = f.read()
        assert actual[796:] == exp.file_contents["src/parser/lexer.c"][796:]

    def test_readme_valid_start(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "docs/README.txt"), "rb") as f:
            actual = f.read()
        assert actual[:1242] == exp.file_contents["docs/README.txt"][:1242]

    def test_readme_zeroed_end(self):
        with open(os.path.join(FILES_DIR, "docs/README.txt"), "rb") as f:
            actual = f.read()
        assert actual[1242:] == b"\x00" * (1800 - 1242)

    def test_api_reference_zeroed_start(self):
        with open(os.path.join(FILES_DIR, "docs/api_reference.md"), "rb") as f:
            actual = f.read()
        assert actual[:1490] == b"\x00" * 1490

    def test_api_reference_valid_rest(self):
        exp = get_expected()
        with open(os.path.join(FILES_DIR, "docs/api_reference.md"), "rb") as f:
            actual = f.read()
        assert actual[1490:] == \
            exp.file_contents["docs/api_reference.md"][1490:]
