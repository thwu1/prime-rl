"""
UCA multi-component collation pipeline correctness tests.

Verifies the C shared library, Python collator, conformance test results,
and SQLite3 sorted output are all correct.

"""

import ast
import ctypes
import os
import sys
import unicodedata

import pytest

sys.path.insert(0, "/app")

ALLKEYS = "/app/data/allkeys.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_conformance(collator, test_file, limit):
    """Return the number of ordering violations in the first *limit* data
    lines of *test_file*."""
    violations = 0
    prev_key = None
    prev_str = None
    data_line = 0

    with open(test_file, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            hex_part = line.split(";")[0].strip() if ";" in line else line
            if not hex_part:
                continue

            data_line += 1
            if data_line > limit:
                break

            cps = [int(tok, 16) for tok in hex_part.split()]
            chars = []
            skip = False
            for cp in cps:
                if 0xD800 <= cp <= 0xDFFF:
                    skip = True
                    break
                try:
                    chars.append(chr(cp))
                except (ValueError, OverflowError):
                    skip = True
                    break
            if skip or not chars:
                prev_key = None
                prev_str = None
                continue

            s = "".join(chars)
            try:
                key = collator.sort_key(s)
            except Exception:
                violations += 1
                prev_key = None
                prev_str = None
                continue

            if prev_key is not None:
                if key < prev_key:
                    violations += 1
                elif key == prev_key:
                    n1 = unicodedata.normalize("NFD", prev_str)
                    n2 = unicodedata.normalize("NFD", s)
                    if n1 > n2:
                        violations += 1

            prev_key = key
            prev_str = s

    return violations


# ---------------------------------------------------------------------------
# C Library Tests
# ---------------------------------------------------------------------------

class TestCLibrary:
    """The C shared library must be built, loadable, and produce correct
    implicit weight values."""

    def test_library_file_exists(self):
        assert os.path.isfile("/app/lib/libimplicit.so"), \
            "libimplicit.so not found at /app/lib/ — the Makefile must produce a shared library"

    def test_library_is_loadable(self):
        lib = ctypes.CDLL("/app/lib/libimplicit.so")
        assert hasattr(lib, "compute_implicit_weight"), \
            "compute_implicit_weight symbol not found in libimplicit.so"

    def test_implicit_weight_core_han_U4E00(self):
        """Core Han U+4E00: AAAA = 0xFB40 + (0x4E00 >> 15) = 0xFB40,
        BBBB = (0x4E00 & 0x7FFF) | 0x8000 = 0xCE00."""
        lib = ctypes.CDLL("/app/lib/libimplicit.so")

        class IW(ctypes.Structure):
            _fields_ = [("aaaa", ctypes.c_uint32), ("bbbb", ctypes.c_uint32)]

        class IR(ctypes.Structure):
            _fields_ = [("start", ctypes.c_uint32), ("end", ctypes.c_uint32),
                        ("base", ctypes.c_uint32)]

        lib.compute_implicit_weight.restype = IW
        lib.compute_implicit_weight.argtypes = [
            ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(IR), ctypes.c_int
        ]

        result = lib.compute_implicit_weight(0x4E00, 1, None, 0)
        assert result.aaaa == 0xFB40, \
            f"Core Han U+4E00 AAAA: expected 0xFB40, got 0x{result.aaaa:04X}"
        assert result.bbbb == 0xCE00, \
            f"Core Han U+4E00 BBBB: expected 0xCE00, got 0x{result.bbbb:04X}"

    def test_implicit_weight_extension_b_U20000(self):
        """CJK Extension B U+20000: AAAA = 0xFB80 + (0x20000 >> 15) = 0xFB84,
        BBBB = (0x20000 & 0x7FFF) | 0x8000 = 0x8000."""
        lib = ctypes.CDLL("/app/lib/libimplicit.so")

        class IW(ctypes.Structure):
            _fields_ = [("aaaa", ctypes.c_uint32), ("bbbb", ctypes.c_uint32)]

        class IR(ctypes.Structure):
            _fields_ = [("start", ctypes.c_uint32), ("end", ctypes.c_uint32),
                        ("base", ctypes.c_uint32)]

        lib.compute_implicit_weight.restype = IW
        lib.compute_implicit_weight.argtypes = [
            ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(IR), ctypes.c_int
        ]

        result = lib.compute_implicit_weight(0x20000, 1, None, 0)
        assert result.aaaa == 0xFB84, \
            f"Extension B U+20000 AAAA: expected 0xFB84, got 0x{result.aaaa:04X}"
        assert result.bbbb == 0x8000, \
            f"Extension B U+20000 BBBB: expected 0x8000, got 0x{result.bbbb:04X}"

    def test_implicit_weight_unassigned(self):
        """Unassigned code point U+EFFFF: AAAA = 0xFBC0 + (0xEFFFF >> 15) = 0xFBDD,
        BBBB = (0xEFFFF & 0x7FFF) | 0x8000 = 0xFFFF."""
        lib = ctypes.CDLL("/app/lib/libimplicit.so")

        class IW(ctypes.Structure):
            _fields_ = [("aaaa", ctypes.c_uint32), ("bbbb", ctypes.c_uint32)]

        class IR(ctypes.Structure):
            _fields_ = [("start", ctypes.c_uint32), ("end", ctypes.c_uint32),
                        ("base", ctypes.c_uint32)]

        lib.compute_implicit_weight.restype = IW
        lib.compute_implicit_weight.argtypes = [
            ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(IR), ctypes.c_int
        ]

        result = lib.compute_implicit_weight(0xEFFFF, 0, None, 0)
        expected_aaaa = 0xFBC0 + (0xEFFFF >> 15)
        expected_bbbb = (0xEFFFF & 0x7FFF) | 0x8000
        assert result.aaaa == expected_aaaa, \
            f"Unassigned U+EFFFF AAAA: expected 0x{expected_aaaa:04X}, got 0x{result.aaaa:04X}"
        assert result.bbbb == expected_bbbb, \
            f"Unassigned U+EFFFF BBBB: expected 0x{expected_bbbb:04X}, got 0x{result.bbbb:04X}"


# ---------------------------------------------------------------------------
# Implementation integrity
# ---------------------------------------------------------------------------

class TestImplementationIntegrity:
    """Verify the implementation is self-contained and complete."""

    def test_no_external_collation_libraries(self):
        """Only standard library modules plus ctypes are permitted."""
        with open("/app/collator.py") as f:
            source = f.read()
        tree = ast.parse(source)
        allowed = {
            "re", "unicodedata", "sys", "os", "collections",
            "functools", "typing", "enum", "dataclasses",
            "abc", "itertools", "operator", "math",
            "ctypes", "sqlite3", "struct",
        }
        banned_names = {"pyuca", "icu", "pyicu", "PyICU"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    assert mod not in banned_names, \
                        f"External collation library '{alias.name}' is not permitted"
                    assert mod in allowed, \
                        f"External dependency '{alias.name}' not allowed"
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                assert mod not in banned_names, \
                    f"External collation library '{node.module}' is not permitted"
                assert mod in allowed, \
                    f"External dependency '{node.module}' not allowed"

    def test_no_unimplemented_stubs(self):
        """All algorithm methods must be implemented (no NotImplementedError)."""
        with open("/app/collator.py") as f:
            source = f.read()
        assert "NotImplementedError" not in source, \
            "Unimplemented stubs remain in collator.py"


# ---------------------------------------------------------------------------
# Sort key structure
# ---------------------------------------------------------------------------

class TestSortKeyStructure:
    """sort_key() must return comparable tuples of integers."""

    def test_returns_tuple_of_ints(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        k = c.sort_key("a")
        assert isinstance(k, tuple)
        assert all(isinstance(w, int) for w in k)

    def test_empty_string(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        k = c.sort_key("")
        assert isinstance(k, tuple)

    def test_key_ordering_reflects_string_ordering(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.sort_key("a") < c.sort_key("b")
        assert c.sort_key("A") < c.sort_key("B")

    def test_shifted_key_is_tuple(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        k = c.sort_key("hello")
        assert isinstance(k, tuple)
        assert all(isinstance(w, int) for w in k)


# ---------------------------------------------------------------------------
# Character ordering
# ---------------------------------------------------------------------------

class TestCharacterOrdering:
    """Verify ordering of specific character pairs under NON_IGNORABLE."""

    def test_latin_letter_order(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.compare("a", "z") < 0
        assert c.compare("m", "n") < 0

    def test_case_as_tertiary_difference(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        k_lower = c.sort_key("a")
        k_upper = c.sort_key("A")
        assert k_lower != k_upper
        assert k_lower < k_upper

    def test_accented_character_order(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.compare("a", "\u00E1") < 0  # a < á

    def test_canonical_equivalence_a_diaeresis(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.sort_key("\u00E4") == c.sort_key("a\u0308")

    def test_canonical_equivalence_c_cedilla(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.sort_key("\u00E7") == c.sort_key("c\u0327")

    def test_string_prefix_ordering(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.compare("abc", "abcd") < 0


# ---------------------------------------------------------------------------
# Supplementary plane and CJK
# ---------------------------------------------------------------------------

class TestSupplementaryOrdering:
    """Code points outside the BMP must produce valid sort keys via
    implicit weight computation."""

    def test_cross_plane_ordering(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.compare(chr(0x40001), chr(0x50001)) < 0

    def test_cjk_basic_has_valid_key(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        k1 = c.sort_key("\u4E00")
        k2 = c.sort_key("\u4E01")
        assert isinstance(k1, tuple) and len(k1) > 0
        assert isinstance(k2, tuple) and len(k2) > 0

    def test_cjk_extension_b_has_valid_key(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        k = c.sort_key(chr(0x20000))
        assert isinstance(k, tuple) and len(k) > 0

    def test_adjacent_unassigned_ordering(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.compare(chr(0x4FFFF), chr(0x50000)) < 0


# ---------------------------------------------------------------------------
# Variable weighting modes
# ---------------------------------------------------------------------------

class TestWeightingModes:
    """Both NON_IGNORABLE and SHIFTED modes must produce valid orderings."""

    def test_shifted_punctuation_ordering(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        assert c.compare("\t", " ") < 0

    def test_shifted_distinct_variable_keys(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        keys = set()
        for ch in "\t\n\r !\"#$%&'()*+,-./:":
            keys.add(c.sort_key(ch))
        assert len(keys) >= 10, \
            f"Expected >= 10 distinct sort keys for variable chars, got {len(keys)}"

    def test_modes_produce_different_keys_for_variables(self):
        from collator import UCACollator
        c_ni = UCACollator(ALLKEYS, "NON_IGNORABLE")
        c_sh = UCACollator(ALLKEYS, "SHIFTED")
        k_ni = c_ni.sort_key(" ")
        k_sh = c_sh.sort_key(" ")
        assert k_ni != k_sh

    def test_shifted_preserves_letter_ordering(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        assert c.compare("abc", "abd") < 0
        assert c.compare("hello", "world") < 0

    def test_shifted_letter_after_variable_correct(self):
        """After a variable element, the after_variable state must be properly
        managed for subsequent non-variable CEs."""
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        assert c.compare(" a", " b") < 0
        assert c.compare("!a", "!b") < 0


# ---------------------------------------------------------------------------
# Compare method
# ---------------------------------------------------------------------------

class TestCompare:
    """compare() must return -1, 0, or 1 with NFD identical-level tiebreaking."""

    def test_compare_returns_int(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        assert c.compare("a", "b") == -1
        assert c.compare("b", "a") == 1
        assert c.compare("a", "a") == 0

    def test_compare_shifted(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        assert c.compare("a", "b") == -1
        assert c.compare("b", "a") == 1
        assert c.compare("a", "a") == 0


# ---------------------------------------------------------------------------
# Official conformance tests
# ---------------------------------------------------------------------------

class TestConformance:
    """Full conformance against official UCA test data (5000 lines each)."""

    def test_non_ignorable_conformance(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")
        violations = _run_conformance(
            c, "/app/data/CollationTest_NON_IGNORABLE_SHORT.txt", limit=5000,
        )
        assert violations == 0, \
            f"{violations} ordering violations in NON_IGNORABLE (first 5000 lines)"

    def test_shifted_conformance(self):
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "SHIFTED")
        violations = _run_conformance(
            c, "/app/data/CollationTest_SHIFTED_SHORT.txt", limit=5000,
        )
        assert violations == 0, \
            f"{violations} ordering violations in SHIFTED (first 5000 lines)"


# ---------------------------------------------------------------------------
# SQLite3 sorted output
# ---------------------------------------------------------------------------

class TestSQLiteOutput:
    """The SQLite3 custom collation must produce correctly sorted output."""

    def test_sorted_output_file_exists(self):
        assert os.path.isfile("/app/output/sorted_multilingual.txt"), \
            "Sorted output not found at /app/output/sorted_multilingual.txt"

    def test_sorted_output_has_expected_lines(self):
        with open("/app/output/sorted_multilingual.txt", "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) >= 20, \
            f"Expected >= 20 sorted lines, got {len(lines)}"

    def test_sorted_output_is_uca_ordered(self):
        """Every adjacent pair in the output must be in correct UCA order."""
        from collator import UCACollator
        c = UCACollator(ALLKEYS, "NON_IGNORABLE")

        with open("/app/output/sorted_multilingual.txt", "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        violations = []
        for i in range(len(lines) - 1):
            cmp = c.compare(lines[i], lines[i + 1])
            if cmp > 0:
                violations.append(
                    f"  line {i}: {lines[i]!r} > line {i+1}: {lines[i+1]!r}"
                )
        assert len(violations) == 0, \
            f"{len(violations)} ordering violations in SQLite3 output:\n" + \
            "\n".join(violations[:10])
