
"""Tests for UAX#29 grapheme cluster segmentation and GraphemeCursor."""

import os
import re
import sys
import pytest

sys.path.insert(0, "/app")

from segmenter.grapheme import (
    grapheme_clusters,
    GraphemeCursor,
    NextChunk,
    PrevChunk,
    PreContext,
)


# ---------------------------------------------------------------------------
# Parse official Unicode GraphemeBreakTest.txt
# ---------------------------------------------------------------------------

def _parse_grapheme_break_test(filepath):
    """Parse GraphemeBreakTest.txt into (full_text, expected_clusters) pairs."""
    tests = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            comment_idx = line.find("#")
            if comment_idx >= 0:
                line = line[:comment_idx]
            line = line.strip()
            if not line:
                continue

            tokens = re.findall(r"[÷×]|[0-9A-Fa-f]+", line)
            clusters = []
            current = []
            for tok in tokens:
                if tok == "÷":
                    if current:
                        clusters.append("".join(chr(cp) for cp in current))
                        current = []
                elif tok == "×":
                    pass
                else:
                    current.append(int(tok, 16))
            if current:
                clusters.append("".join(chr(cp) for cp in current))

            full_text = "".join(clusters)
            tests.append((full_text, clusters))
    return tests


_TEST_FILE = "/app/data/GraphemeBreakTest.txt"
_OFFICIAL_TESTS = (
    _parse_grapheme_break_test(_TEST_FILE) if os.path.exists(_TEST_FILE) else []
)


# ---------------------------------------------------------------------------
# Helper: iterate via cursor over a chunked string
# ---------------------------------------------------------------------------

def _cursor_boundaries_chunked(text, chunk_boundaries):
    """Use GraphemeCursor.next_boundary to find all boundaries with given chunk splits."""
    if not text:
        return [0]
    chunks = []
    starts = []
    prev = 0
    for b in chunk_boundaries:
        chunks.append(text[prev:b])
        starts.append(prev)
        prev = b
    chunks.append(text[prev:])
    starts.append(prev)

    cursor = GraphemeCursor(0, len(text), is_extended=True)
    boundaries = [0]
    ci = 0  # current chunk index

    while True:
        try:
            b = cursor.next_boundary(chunks[ci], starts[ci])
            if b is None:
                break
            boundaries.append(b)
        except NextChunk:
            ci += 1
            if ci >= len(chunks):
                break
        except PreContext as e:
            # Find chunk that ends at e.offset
            for j in range(len(chunks)):
                if starts[j] + len(chunks[j]) == e.offset:
                    cursor.provide_context(chunks[j], starts[j])
                    break
            else:
                # Provide empty context at start
                if e.offset == 0:
                    cursor.provide_context("", 0)
                else:
                    raise RuntimeError(f"Cannot find chunk ending at {e.offset}")

    boundaries.append(len(text))
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for b in boundaries:
        if b not in seen:
            seen.add(b)
            deduped.append(b)
    return deduped


def _boundaries_to_clusters(text, boundaries):
    return [text[boundaries[i] : boundaries[i + 1]] for i in range(len(boundaries) - 1)]


# ---------------------------------------------------------------------------
# Tests: Official conformance
# ---------------------------------------------------------------------------

class TestOfficialConformance:
    """Test against official Unicode 17.0 GraphemeBreakTest.txt vectors."""

    @pytest.mark.parametrize(
        "text,expected",
        _OFFICIAL_TESTS[:200],
        ids=[f"official_{i}" for i in range(min(200, len(_OFFICIAL_TESTS)))],
    )
    def test_first_200(self, text, expected):
        result = grapheme_clusters(text)
        assert result == expected, (
            f"Input: {[hex(ord(c)) for c in text]}\n"
            f"Expected: {[[hex(ord(c)) for c in cl] for cl in expected]}\n"
            f"Got:      {[[hex(ord(c)) for c in cl] for cl in result]}"
        )

    @pytest.mark.parametrize(
        "text,expected",
        _OFFICIAL_TESTS[200:],
        ids=[f"official_{i}" for i in range(200, len(_OFFICIAL_TESTS))],
    )
    def test_remaining(self, text, expected):
        result = grapheme_clusters(text)
        assert result == expected


# ---------------------------------------------------------------------------
# Tests: Specific edge cases (whole-string mode)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty(self):
        assert grapheme_clusters("") == []

    def test_ascii(self):
        assert grapheme_clusters("abc") == ["a", "b", "c"]

    def test_crlf(self):
        assert grapheme_clusters("\r\n") == ["\r\n"]
        assert grapheme_clusters("\r\n\r\n") == ["\r\n", "\r\n"]

    def test_cr_alone(self):
        assert grapheme_clusters("\r") == ["\r"]
        assert grapheme_clusters("\ra") == ["\r", "a"]

    def test_regional_indicators_two(self):
        # Two RI = one flag (one cluster)
        text = "\U0001F1FA\U0001F1F8"  # US flag
        result = grapheme_clusters(text)
        assert result == [text]

    def test_regional_indicators_four(self):
        # Four RI = two flags
        text = "\U0001F1F7\U0001F1F8\U0001F1EE\U0001F1F4"
        result = grapheme_clusters(text)
        assert len(result) == 2
        assert result[0] == "\U0001F1F7\U0001F1F8"
        assert result[1] == "\U0001F1EE\U0001F1F4"

    def test_regional_indicators_three(self):
        # Three RI: first two pair, third is alone
        text = "\U0001F1FA\U0001F1F8\U0001F1EE"
        result = grapheme_clusters(text)
        assert len(result) == 2

    def test_zwj_emoji(self):
        # Family emoji: woman + ZWJ + woman + ZWJ + boy
        text = "\U0001F469\u200D\U0001F469\u200D\U0001F466"
        result = grapheme_clusters(text)
        assert result == [text]

    def test_emoji_no_zwj(self):
        # Two emoji without ZWJ = separate clusters
        text = "\U0001F352\U0001F951"
        result = grapheme_clusters(text)
        assert result == ["\U0001F352", "\U0001F951"]

    def test_emoji_zwj(self):
        # Emoji + ZWJ + emoji = one cluster
        text = "\U0001F352\u200D\U0001F951"
        result = grapheme_clusters(text)
        assert result == [text]

    def test_emoji_extend_zwj(self):
        # Extended_Pictographic + Extend + ZWJ + Extended_Pictographic
        text = "\U0001F469\U0001F3FB\u200D\U0001F52C"
        result = grapheme_clusters(text)
        assert result == [text]

    def test_indic_conjunct(self):
        # Devanagari: ka + virama + ka = one cluster (GB9c)
        text = "\u0915\u094D\u0915"
        result = grapheme_clusters(text)
        assert result == [text]

    def test_indic_conjunct_no_linker(self):
        # Devanagari: ka + ka = two clusters (no virama)
        text = "\u0915\u0915"
        result = grapheme_clusters(text)
        assert result == ["\u0915", "\u0915"]

    def test_hangul_lv(self):
        # Hangul LV syllable + trailing consonant
        text = "\uAC00\u11A8"  # LV + T
        result = grapheme_clusters(text)
        assert result == [text]

    def test_prepend(self):
        text = "\u0600a"
        result = grapheme_clusters(text)
        assert result == ["\u0600a"]


# ---------------------------------------------------------------------------
# Tests: Chunked cursor equivalence
# ---------------------------------------------------------------------------

class TestCursorEquivalence:
    """Verify GraphemeCursor produces the same results as grapheme_clusters()."""

    _TEST_STRINGS = [
        "hello world",
        "\r\n\r\n",
        "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F4",  # two flags
        "\U0001F469\u200D\U0001F469\u200D\U0001F466",  # ZWJ family
        "\U0001F352\u200D\U0001F951",                  # cherry ZWJ avocado
        "\U0001F352\U0001F951",                        # cherry, avocado (no ZWJ)
        "\u0915\u094D\u0915",                          # Devanagari conjunct
        "\u0915\u094D\u0300\u0915",                    # conjunct with extend
        "\u0600abc",                                   # prepend
        "\U0001F469\U0001F3FB\u200D\U0001F52C",        # emoji + skin tone + ZWJ + emoji
        "a\u0308b",                                    # a + combining diaeresis + b
        "\U0001F1FA\U0001F1F8\U0001F1FA\U0001F1F8\U0001F1FA\U0001F1F8",  # 6 RI
    ]

    @pytest.mark.parametrize("text", _TEST_STRINGS)
    def test_single_char_chunks(self, text):
        """Split at every character boundary — hardest chunking scenario."""
        expected = grapheme_clusters(text)
        for split_at in range(1, len(text)):
            boundaries = _cursor_boundaries_chunked(text, [split_at])
            result = _boundaries_to_clusters(text, boundaries)
            assert result == expected, (
                f"Failed with split at {split_at} for "
                f"{[hex(ord(c)) for c in text]}"
            )

    @pytest.mark.parametrize("text", _TEST_STRINGS)
    def test_all_single_char_chunks(self, text):
        """Every character is its own chunk."""
        expected = grapheme_clusters(text)
        chunk_bounds = list(range(1, len(text)))
        boundaries = _cursor_boundaries_chunked(text, chunk_bounds)
        result = _boundaries_to_clusters(text, boundaries)
        assert result == expected

    def test_whole_string_chunk(self):
        """Entire string as one chunk should work identically."""
        for text in self._TEST_STRINGS:
            expected = grapheme_clusters(text)
            boundaries = _cursor_boundaries_chunked(text, [])
            result = _boundaries_to_clusters(text, boundaries)
            assert result == expected


# ---------------------------------------------------------------------------
# Tests: Specific chunked edge cases
# ---------------------------------------------------------------------------

class TestCursorChunkedEdgeCases:
    def test_emoji_zwj_across_chunks(self):
        """ZWJ emoji sequence split between two chunks."""
        chunk0 = "\U0001F469"       # woman emoji (Extended_Pictographic)
        chunk1 = "\u200D\U0001F52C" # ZWJ + microscope
        text = chunk0 + chunk1
        expected = grapheme_clusters(text)

        cursor = GraphemeCursor(0, len(text))
        boundaries = [0]

        try:
            b = cursor.next_boundary(chunk0, 0)
            if b is not None:
                boundaries.append(b)
        except NextChunk:
            pass

        while True:
            try:
                b = cursor.next_boundary(chunk1, len(chunk0))
                if b is None:
                    break
                boundaries.append(b)
            except PreContext as e:
                cursor.provide_context(chunk0, 0)

        boundaries.append(len(text))
        seen = set()
        deduped = [b for b in boundaries if b not in seen and not seen.add(b)]
        result = _boundaries_to_clusters(text, deduped)
        assert result == expected

    def test_ris_precontext(self):
        """Regional Indicators requiring pre-context across chunks."""
        flags = "\U0001F1FA\U0001F1F8\U0001F1FA\U0001F1F8"
        expected = grapheme_clusters(flags)
        assert len(expected) == 2

        # Split at the boundary between the two flags
        mid = 2
        boundaries = _cursor_boundaries_chunked(flags, [mid])
        result = _boundaries_to_clusters(flags, boundaries)
        assert result == expected

    def test_indic_across_chunks(self):
        """Indic conjunct break (GB9c) across chunk boundary."""
        # ka + virama | ka  (virama is InCB=Linker)
        text = "\u0915\u094D\u0915"
        expected = grapheme_clusters(text)
        assert expected == [text]

        # Split after virama
        boundaries = _cursor_boundaries_chunked(text, [2])
        result = _boundaries_to_clusters(text, boundaries)
        assert result == expected

    def test_crlf_across_chunks(self):
        """CR+LF split across chunk boundary."""
        text = "\r\n"
        expected = grapheme_clusters(text)
        boundaries = _cursor_boundaries_chunked(text, [1])
        result = _boundaries_to_clusters(text, boundaries)
        assert result == expected

    def test_emoji_zwj_three_chunks(self):
        """Emoji + ZWJ + Emoji split across three chunks."""
        chunk0 = "\U0001F352"  # cherry
        chunk1 = "\u200D"      # ZWJ
        chunk2 = "\U0001F951"  # avocado
        text = chunk0 + chunk1 + chunk2
        expected = grapheme_clusters(text)
        assert expected == [text]

        boundaries = _cursor_boundaries_chunked(text, [1, 2])
        result = _boundaries_to_clusters(text, boundaries)
        assert result == expected


# ---------------------------------------------------------------------------
# Tests: Bidirectional iteration
# ---------------------------------------------------------------------------

class TestPrevBoundary:
    _TEST_STRINGS = [
        "abcd",
        "\r\n\r\n",
        "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F4",
        "\U0001F352\u200D\U0001F951",
        "\u0915\u094D\u0915",
        "a\u0308b",
    ]

    @pytest.mark.parametrize("text", _TEST_STRINGS)
    def test_prev_matches_forward(self, text):
        """prev_boundary iteration should yield same boundaries as forward."""
        forward = grapheme_clusters(text)
        # Compute forward boundaries
        fwd_bounds = [0]
        pos = 0
        for cl in forward:
            pos += len(cl)
            fwd_bounds.append(pos)

        # Iterate backward with cursor
        cursor = GraphemeCursor(len(text), len(text))
        rev_bounds = [len(text)]
        while True:
            try:
                b = cursor.prev_boundary(text, 0)
                if b is None:
                    break
                rev_bounds.append(b)
            except PreContext:
                raise  # shouldn't happen with full string

        rev_bounds.sort()
        assert rev_bounds == fwd_bounds, (
            f"Forward: {fwd_bounds}, Backward: {rev_bounds}"
        )
