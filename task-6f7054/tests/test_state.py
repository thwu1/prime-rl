
import json
import os
import numpy as np
import pytest


BINARY_PATH = "/app/cipher_module"
REPORT_PATH = "/app/report.json"


def extract_permutation_tables(path):
    """Scan a binary file for 256-byte sequences that are permutations of {0,...,255}."""
    with open(path, "rb") as f:
        data = f.read()

    tables = []
    i = 0
    while i <= len(data) - 256:
        candidate = list(data[i : i + 256])
        if sorted(candidate) == list(range(256)):
            tables.append(candidate)
            i += 256
        else:
            i += 1
    return tables


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def ddt_row_multiset(sbox_arr):
    """Compute the canonical DDT row multiset fingerprint.

    Each DDT row is converted to a sorted tuple of counts, then the
    collection of all 256 such tuples is sorted to produce an
    order-independent fingerprint invariant under composition with
    invertible GF(2)-linear maps (which merely permute DDT rows/columns).
    """
    N = len(sbox_arr)
    sbox_np = np.array(sbox_arr, dtype=np.int32)
    rows = []
    for dx in range(N):
        shifted = np.arange(N, dtype=np.int32) ^ dx
        dy = sbox_np ^ sbox_np[shifted]
        counts = np.bincount(dy, minlength=N)
        rows.append(tuple(sorted(counts.tolist())))
    return tuple(sorted(rows))


def is_modular_affine(perm):
    """Check if perm represents x -> a*x + b mod 256 for some odd a and some b."""
    if len(perm) != 256:
        return False
    b = perm[0]
    a = (perm[1] - b) % 256
    if a == 0 or a % 2 == 0:
        return False
    for x in range(256):
        if perm[x] != (a * x + b) % 256:
            return False
    return True


class TestCipherModuleEvaluation:
    """Verify that the submitted security evaluation correctly identifies
    the vulnerability and produces a valid algebraic core permutation."""

    _tables = None

    @classmethod
    def get_tables(cls):
        if cls._tables is None:
            cls._tables = extract_permutation_tables(BINARY_PATH)
        return cls._tables

    def test_binary_exists(self):
        assert os.path.exists(BINARY_PATH), "cipher_module binary not found"

    def test_tables_extracted(self):
        tables = self.get_tables()
        assert len(tables) >= 2, (
            f"Expected at least 2 permutation tables in binary, found {len(tables)}"
        )

    def test_report_file_exists(self):
        assert os.path.exists(REPORT_PATH), "report.json not found in /app/"

    def test_report_format(self):
        report = load_report()
        assert "vulnerable" in report, "report.json must contain key 'vulnerable'"
        assert "core_permutation" in report, "report.json must contain key 'core_permutation'"

    def test_vulnerability_assessment(self):
        """The substitution tables are genuinely weak; vulnerable must be true."""
        report = load_report()
        assert report["vulnerable"] is True, (
            "Incorrect assessment: the substitution tables ARE vulnerable"
        )

    def test_core_permutation_is_list(self):
        report = load_report()
        perm = report["core_permutation"]
        assert isinstance(perm, list), "core_permutation must be a list"
        assert len(perm) == 256, f"core_permutation must have 256 elements, got {len(perm)}"

    def test_core_permutation_is_permutation(self):
        report = load_report()
        perm = report["core_permutation"]
        assert all(isinstance(v, int) for v in perm), "all elements must be integers"
        assert sorted(perm) == list(range(256)), "core_permutation must be a permutation of 0-255"

    def test_core_is_elementary(self):
        """The core permutation must be a simple modular-arithmetic function,
        not just any affinely equivalent permutation."""
        report = load_report()
        perm = report["core_permutation"]
        assert is_modular_affine(perm), (
            "core_permutation is not a simple modular-arithmetic permutation — "
            "the solver must reduce the S-boxes to their simplest algebraic form"
        )

    def test_core_matches_table1(self):
        """The core permutation must be affinely equivalent to the first S-box."""
        tables = self.get_tables()
        report = load_report()
        perm = report["core_permutation"]

        ddt_table = ddt_row_multiset(tables[0])
        ddt_core = ddt_row_multiset(perm)

        assert ddt_table == ddt_core, (
            "DDT row multiset of core_permutation does not match substitution table 1 — "
            "the submitted permutation is not equivalent to the cipher's S-boxes"
        )

    def test_core_matches_table2(self):
        """The core permutation must be affinely equivalent to the second S-box."""
        tables = self.get_tables()
        report = load_report()
        perm = report["core_permutation"]

        ddt_table = ddt_row_multiset(tables[1])
        ddt_core = ddt_row_multiset(perm)

        assert ddt_table == ddt_core, (
            "DDT row multiset of core_permutation does not match substitution table 2 — "
            "the submitted permutation is not equivalent to the cipher's S-boxes"
        )

    def test_both_tables_share_structure(self):
        """Sanity check: both embedded tables should share the same DDT structure."""
        tables = self.get_tables()
        ddt_1 = ddt_row_multiset(tables[0])
        ddt_2 = ddt_row_multiset(tables[1])
        assert ddt_1 == ddt_2, "The two substitution tables do not share the same DDT structure"
