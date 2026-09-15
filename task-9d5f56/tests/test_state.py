"""
Verify Unicode UAX #29 text segmentation against official conformance test suites.
Also validates the required C shared library + ICU + ctypes build infrastructure.
"""

import subprocess
import sys
import os

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Build infrastructure tests
# ---------------------------------------------------------------------------

def test_shared_library_exists():
    """libpropdb.so must exist at /app/."""
    assert os.path.exists('/app/libpropdb.so'), \
        "Compiled shared library /app/libpropdb.so not found"


def test_library_links_icu():
    """libpropdb.so must dynamically link against libicuuc (ICU4C)."""
    result = subprocess.run(
        ['ldd', '/app/libpropdb.so'],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"ldd failed: {result.stderr}"
    assert 'libicuuc' in result.stdout, \
        "libpropdb.so must link against libicuuc (ICU4C). " \
        f"ldd output:\n{result.stdout}"


def test_makefile_uses_icu_tools():
    """Makefile must exist and reference pkg-config or icu-config."""
    assert os.path.exists('/app/Makefile'), "/app/Makefile not found"
    with open('/app/Makefile') as f:
        content = f.read()
    assert 'pkg-config' in content or 'icu-config' in content, \
        "Makefile must use pkg-config or icu-config for ICU flags"


def test_segmenter_uses_ctypes():
    """segmenter.py must load the C library via ctypes."""
    assert os.path.exists('/app/segmenter.py'), "/app/segmenter.py not found"
    with open('/app/segmenter.py') as f:
        content = f.read()
    assert 'ctypes' in content, \
        "segmenter.py must use Python ctypes to load the C shared library"


# ---------------------------------------------------------------------------
# Conformance test data parsing
# ---------------------------------------------------------------------------

def parse_break_test(filepath):
    """Parse a Unicode break test file.

    Format: alternating break-markers and hex code points.
      \u00f7 = break opportunity, \u00d7 = no break
    Returns list of (codepoints, expected_boundaries, line_number).
    """
    test_cases = []
    with open(filepath, encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            data = line.split('#')[0].strip()
            if not data:
                continue

            tokens = data.split()
            codepoints = []
            boundaries = []
            cp_count = 0

            for token in tokens:
                if token == '\u00f7':        # division sign = break
                    boundaries.append(cp_count)
                elif token == '\u00d7':      # multiplication sign = no break
                    pass
                else:
                    try:
                        codepoints.append(int(token, 16))
                        cp_count += 1
                    except ValueError:
                        pass

            if codepoints:
                test_cases.append((codepoints, sorted(boundaries), line_num))
    return test_cases


GRAPHEME_TESTS = parse_break_test('/app/testdata/GraphemeBreakTest.txt')
WORD_TESTS = parse_break_test('/app/testdata/WordBreakTest.txt')
SENTENCE_TESTS = parse_break_test('/app/testdata/SentenceBreakTest.txt')


# ---------------------------------------------------------------------------
# Segmentation conformance tests
# ---------------------------------------------------------------------------

def test_grapheme_segmentation():
    from segmenter import grapheme_boundaries

    failures = []
    for cps, expected, line_num in GRAPHEME_TESTS:
        result = sorted(grapheme_boundaries(cps))
        if result != expected:
            failures.append((line_num, cps, expected, result))

    total = len(GRAPHEME_TESTS)
    passed = total - len(failures)

    for ln, cps, exp, got in failures[:10]:
        cp_str = ' '.join(f'{c:04X}' for c in cps)
        print(f"FAIL grapheme line {ln}: [{cp_str}] expected={exp} got={got}")

    assert len(failures) == 0, (
        f"Grapheme segmentation: {passed}/{total} passed, "
        f"{len(failures)} failures"
    )


def test_word_segmentation():
    from segmenter import word_boundaries

    failures = []
    for cps, expected, line_num in WORD_TESTS:
        result = sorted(word_boundaries(cps))
        if result != expected:
            failures.append((line_num, cps, expected, result))

    total = len(WORD_TESTS)
    passed = total - len(failures)

    for ln, cps, exp, got in failures[:10]:
        cp_str = ' '.join(f'{c:04X}' for c in cps)
        print(f"FAIL word line {ln}: [{cp_str}] expected={exp} got={got}")

    assert len(failures) == 0, (
        f"Word segmentation: {passed}/{total} passed, "
        f"{len(failures)} failures"
    )


def test_sentence_segmentation():
    from segmenter import sentence_boundaries

    failures = []
    for cps, expected, line_num in SENTENCE_TESTS:
        result = sorted(sentence_boundaries(cps))
        if result != expected:
            failures.append((line_num, cps, expected, result))

    total = len(SENTENCE_TESTS)
    passed = total - len(failures)

    for ln, cps, exp, got in failures[:10]:
        cp_str = ' '.join(f'{c:04X}' for c in cps)
        print(f"FAIL sentence line {ln}: [{cp_str}] expected={exp} got={got}")

    assert len(failures) == 0, (
        f"Sentence segmentation: {passed}/{total} passed, "
        f"{len(failures)} failures"
    )
