"""
Conformance tests for Unicode 16.0 sentence boundary segmentation.

Validates sentence segmentation against official Unicode test vectors
and verifies edge cases, property lookups, and implementation quality.

"""

import os
import sys

sys.path.insert(0, '/app')


def parse_test_vectors(filepath):
    """Parse Unicode break test file (div/times marker format)."""
    tests = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for lineno, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if '#' in line:
                line = line[:line.index('#')].strip()
            if not line:
                continue

            tokens = line.split()
            codepoints = []
            markers = []
            skip = False

            for tok in tokens:
                if tok == '\u00f7':
                    markers.append(True)
                elif tok == '\u00d7':
                    markers.append(False)
                else:
                    cp = int(tok, 16)
                    if 0xD800 <= cp <= 0xDFFF:
                        skip = True
                        break
                    codepoints.append(cp)

            if skip or not codepoints:
                continue

            text = ''.join(chr(cp) for cp in codepoints)
            segments = []
            current = chr(codepoints[0])
            for i in range(1, len(codepoints)):
                if markers[i]:
                    segments.append(current)
                    current = chr(codepoints[i])
                else:
                    current += chr(codepoints[i])
            segments.append(current)
            tests.append((text, segments, lineno))
    return tests


def _fmt(s):
    """Format a string as U+XXXX codepoint sequence."""
    return ' '.join(f'U+{ord(c):04X}' for c in s)


def _fmt_segs(segs):
    return ' | '.join(_fmt(s) for s in segs)


# Load test vectors at module level
SENTENCE_VECTORS = parse_test_vectors('/app/data/SentenceBreakTest.txt')

# Import segmenters
_s_err = None
try:
    from sentence_segment import segment_sentences, sentence_break_property
except Exception as e:
    segment_sentences = None
    sentence_break_property = None
    _s_err = str(e)


class TestSentenceConformance:
    """Full SentenceBreakTest.txt conformance."""

    def test_sentence_import(self):
        assert segment_sentences is not None, f"Import failed: {_s_err}"

    def test_sentence_vector_count(self):
        assert len(SENTENCE_VECTORS) > 50, (
            f"Only {len(SENTENCE_VECTORS)} sentence vectors, expected > 50"
        )

    def test_all_sentence_vectors(self):
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        failures = []
        for text, expected, lineno in SENTENCE_VECTORS:
            result = segment_sentences(text)
            if result != expected:
                failures.append(
                    f"  line {lineno}: {_fmt(text)}\n"
                    f"    expected: [{_fmt_segs(expected)}]\n"
                    f"    got:      [{_fmt_segs(result)}]"
                )
        assert not failures, (
            f"{len(failures)}/{len(SENTENCE_VECTORS)} sentence test(s) failed:\n"
            + '\n'.join(failures[:30])
            + ('\n  ...' if len(failures) > 30 else '')
        )

    def test_sentence_concatenation_identity(self):
        """Segments must concatenate to the original text."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        for text, _, lineno in SENTENCE_VECTORS:
            result = segment_sentences(text)
            assert ''.join(result) == text, (
                f"line {lineno}: sentence segments don't reconstruct input"
            )

    def test_sentence_empty(self):
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        assert segment_sentences('') == []


class TestSentencePropertyLookups:
    """Verify sentence break property lookup infrastructure."""

    def test_sentence_break_property_aterm(self):
        assert sentence_break_property is not None, f"Import failed: {_s_err}"
        assert sentence_break_property('.') == 'ATerm'

    def test_sentence_break_property_sterm(self):
        assert sentence_break_property is not None, f"Import failed: {_s_err}"
        assert sentence_break_property('!') == 'STerm'
        assert sentence_break_property('?') == 'STerm'

    def test_sentence_break_property_letters(self):
        assert sentence_break_property is not None, f"Import failed: {_s_err}"
        assert sentence_break_property('a') == 'Lower'
        assert sentence_break_property('A') == 'Upper'

    def test_sentence_break_property_numeric(self):
        assert sentence_break_property is not None, f"Import failed: {_s_err}"
        assert sentence_break_property('0') == 'Numeric'

    def test_sentence_break_property_line_endings(self):
        assert sentence_break_property is not None, f"Import failed: {_s_err}"
        assert sentence_break_property('\r') == 'CR'
        assert sentence_break_property('\n') == 'LF'

    def test_sentence_break_property_space(self):
        assert sentence_break_property is not None, f"Import failed: {_s_err}"
        assert sentence_break_property(' ') == 'Sp'

    def test_sentence_shared_library_exists(self):
        assert os.path.isfile('/app/libsentbreak.so'), "Sentence C shared library missing"

    def test_sentence_segment_uses_ctypes(self):
        """sentence_segment.py must use ctypes to load the C library."""
        with open('/app/sentence_segment.py') as f:
            source = f.read()
        assert 'ctypes' in source, (
            "sentence_segment.py must use ctypes to load the C library"
        )


class TestSentenceEdgeCases:
    """Additional edge cases for sentence boundary segmentation."""

    def test_not_trivial_implementation(self):
        """Verify the implementation is not trivially returning single-char segments."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        result = segment_sentences("Hello world. How are you?")
        assert len(result) <= 5, (
            f"Implementation appears trivial: {len(result)} segments for simple text"
        )
        assert len(result) >= 2, (
            f"Only {len(result)} segment(s) for text with two sentences"
        )

    def test_multiple_terminators(self):
        """Multiple sentence terminators produce multiple segments."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        result = segment_sentences("Yes! No! Maybe.")
        assert ''.join(result) == "Yes! No! Maybe."
        assert len(result) == 3

    def test_crlf_not_split(self):
        """CR LF should not be split (SB3)."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        result = segment_sentences("End.\r\nStart.")
        assert ''.join(result) == "End.\r\nStart."
        # CR+LF together act as one paragraph separator
        # SB4 breaks after the CRLF, so we get 2 segments
        assert len(result) == 2

    def test_abbreviation_sb7(self):
        """SB7: (Upper|Lower) ATerm x Upper should not break."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        # U.S. followed by uppercase - SB7 prevents break after first period
        result = segment_sentences("U.S. is great.")
        assert ''.join(result) == "U.S. is great."
        # SB7 prevents break between U. and S,
        # SB8 prevents break after S. because lowercase 'i' follows
        assert len(result) == 1

    def test_sb8_forward_scan(self):
        """SB8: ATerm Close* Sp* x (non-break-set)* Lower."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        # After ATerm+Sp, if forward scan finds Lower before break-set, no break
        result = segment_sentences("etc. and more.")
        assert ''.join(result) == "etc. and more."
        # SB8 finds 'a' (Lower) after ". " so no break
        assert len(result) == 1

    def test_sb8_uppercase_breaks(self):
        """SB8 should NOT prevent break when uppercase follows."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        result = segment_sentences("End. Start.")
        assert ''.join(result) == "End. Start."
        # SB8 forward scan finds 'S' (Upper, in break-set) before any Lower
        # SB11 fires -> break
        assert len(result) == 2

    def test_single_sentence_no_break(self):
        """Text without sentence terminators is one segment."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        result = segment_sentences("hello world")
        assert result == ["hello world"]

    def test_sb8a_scontinue(self):
        """SB8a: sentence continuation after terminator."""
        assert segment_sentences is not None, f"Import failed: {_s_err}"
        # After STerm, a comma (SContinue) should not cause a break
        result = segment_sentences("No!,")
        assert ''.join(result) == "No!,"
        # SB8a prevents break between '!' and ','
        assert len(result) == 1
