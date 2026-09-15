
"""
Tests for fzf match engine — all five match types.
Test vectors extracted from fzf's algo_test.go (junegunn/fzf).
"""

import sys
import pytest

sys.path.insert(0, "/app")
from fzf_match import (
    fuzzy_match_v2,
    exact_match_naive,
    prefix_match,
    suffix_match,
    equal_match,
)


# ═══════════════════════════════════════════════════════════
#  FuzzyMatchV2 — case-insensitive
# ═══════════════════════════════════════════════════════════

class TestFuzzyMatchV2CaseInsensitive:

    def test_camel_case_boundary(self):
        assert fuzzy_match_v2("fooBarbaz1", "oBZ", case_sensitive=False) == (2, 9, 49)

    def test_whitespace_boundaries(self):
        assert fuzzy_match_v2("foo bar baz", "fbb", case_sensitive=False) == (0, 9, 78)

    def test_camel_consecutive(self):
        assert fuzzy_match_v2("/AutomatorDocument.icns", "rdoc", case_sensitive=False) == (9, 13, 79)

    def test_delimiter_boundary(self):
        assert fuzzy_match_v2("/man1/zshcompctl.1", "zshc", case_sensitive=False) == (6, 10, 109)

    def test_mixed_boundary_gap(self):
        assert fuzzy_match_v2("/.oh-my-zsh/cache", "zshc", case_sensitive=False) == (8, 13, 102)

    def test_nonword_start_full(self):
        assert fuzzy_match_v2(".vimrc", ".vimrc", case_sensitive=False) == (0, 6, 166)

    def test_nonword_after_delimiter(self):
        assert fuzzy_match_v2("/.vimrc", ".vimrc", case_sensitive=False) == (1, 7, 159)

    def test_nonword_mid_word(self):
        assert fuzzy_match_v2("a.vimrc", ".vimrc", case_sensitive=False) == (1, 7, 152)

    def test_number_consecutive_gap(self):
        assert fuzzy_match_v2("ab0123 456", "12356", case_sensitive=False) == (3, 10, 88)

    def test_number_camel_boundary(self):
        assert fuzzy_match_v2("abc123 456", "12356", case_sensitive=False) == (3, 10, 108)

    def test_slash_delimiter(self):
        assert fuzzy_match_v2("foo/bar/baz", "fbb", case_sensitive=False) == (0, 9, 76)

    def test_camelcase_acronym(self):
        assert fuzzy_match_v2("fooBarBaz", "fbb", case_sensitive=False) == (0, 7, 74)

    def test_single_whitespace_boundary(self):
        assert fuzzy_match_v2("foo barbaz", "fbb", case_sensitive=False) == (0, 8, 69)

    def test_consecutive_at_start(self):
        assert fuzzy_match_v2("fooBar Baz", "foob", case_sensitive=False) == (0, 4, 114)

    def test_mixed_camel_nonword_boundary(self):
        assert fuzzy_match_v2("xFoo-Bar Baz", "foo-b", case_sensitive=False) == (1, 6, 124)


# ═══════════════════════════════════════════════════════════
#  FuzzyMatchV2 — case-sensitive
# ═══════════════════════════════════════════════════════════

class TestFuzzyMatchV2CaseSensitive:

    def test_case_sensitive_camel(self):
        assert fuzzy_match_v2("fooBarbaz", "oBz", case_sensitive=True) == (2, 9, 49)

    def test_case_sensitive_slash(self):
        assert fuzzy_match_v2("Foo/Bar/Baz", "FBB", case_sensitive=True) == (0, 9, 76)

    def test_case_sensitive_camelcase(self):
        assert fuzzy_match_v2("FooBarBaz", "FBB", case_sensitive=True) == (0, 7, 74)

    def test_case_sensitive_consecutive(self):
        assert fuzzy_match_v2("FooBar Baz", "FooB", case_sensitive=True) == (0, 4, 114)

    def test_case_sensitive_consecutive_bonus(self):
        assert fuzzy_match_v2("foo-bar", "o-ba", case_sensitive=True) == (2, 6, 88)


# ═══════════════════════════════════════════════════════════
#  FuzzyMatchV2 — non-match
# ═══════════════════════════════════════════════════════════

class TestFuzzyNonMatch:

    def test_case_mismatch(self):
        assert fuzzy_match_v2("fooBarbaz", "oBZ", case_sensitive=True) == (-1, -1, 0)

    def test_case_mismatch2(self):
        assert fuzzy_match_v2("Foo Bar Baz", "fbb", case_sensitive=True) == (-1, -1, 0)

    def test_pattern_too_long(self):
        assert fuzzy_match_v2("fooBarbaz", "fooBarbazz", case_sensitive=True) == (-1, -1, 0)

    def test_pattern_too_long_insensitive(self):
        assert fuzzy_match_v2("fooBarbaz", "fooBarbazz", case_sensitive=False) == (-1, -1, 0)


# ═══════════════════════════════════════════════════════════
#  FuzzyMatchV2 — empty pattern, single char, edge cases
# ═══════════════════════════════════════════════════════════

class TestFuzzyEdgeCases:

    def test_empty_pattern(self):
        assert fuzzy_match_v2("foobar", "", case_sensitive=True) == (0, 0, 0)

    def test_empty_pattern_insensitive(self):
        assert fuzzy_match_v2("foobar", "", case_sensitive=False) == (0, 0, 0)

    def test_single_match_start(self):
        assert fuzzy_match_v2("foobar", "f", case_sensitive=False) == (0, 1, 36)

    def test_single_match_boundary(self):
        assert fuzzy_match_v2("foo bar", "b", case_sensitive=False) == (4, 5, 36)

    def test_exact_3_consecutive(self):
        assert fuzzy_match_v2("abc", "abc", case_sensitive=False) == (0, 3, 88)

    def test_delimiter_single_char(self):
        assert fuzzy_match_v2("/b", "b", case_sensitive=False) == (1, 2, 34)

    def test_camel_single_char(self):
        assert fuzzy_match_v2("aB", "b", case_sensitive=False) == (1, 2, 30)

    def test_whitespace_single(self):
        assert fuzzy_match_v2(" a", "a", case_sensitive=False) == (1, 2, 36)

    def test_single_char_text(self):
        assert fuzzy_match_v2("a", "a", case_sensitive=False) == (0, 1, 36)

    def test_no_match(self):
        assert fuzzy_match_v2("abc", "z", case_sensitive=False) == (-1, -1, 0)

    def test_full_match(self):
        result = fuzzy_match_v2("hello", "hello", case_sensitive=False)
        assert result[0] == 0
        assert result[1] == 5
        assert result[2] > 0

    def test_long_gap(self):
        text = "a" + "x" * 20 + "b"
        result = fuzzy_match_v2(text, "ab", case_sensitive=False)
        assert result[0] == 0
        assert result[1] == 22
        assert result[2] > 0

    def test_best_alignment_consecutive(self):
        # Consecutive "ab" at 7-8 should beat separated a...b at 0,4
        assert fuzzy_match_v2("a___b__ab", "ab", case_sensitive=False) == (7, 9, 56)


# ═══════════════════════════════════════════════════════════
#  ExactMatchNaive
# ═══════════════════════════════════════════════════════════

class TestExactMatchNaive:

    def test_case_sensitive_no_match(self):
        assert exact_match_naive("fooBarbaz", "oBA", case_sensitive=True) == (-1, -1, 0)

    def test_pattern_too_long(self):
        assert exact_match_naive("fooBarbaz", "fooBarbazz", case_sensitive=True) == (-1, -1, 0)

    def test_case_insensitive_camel(self):
        # scoreMatch*3 + bonusCamel123 + bonusConsecutive = 48+7+4 = 59
        assert exact_match_naive("fooBarbaz", "oBA", case_sensitive=False) == (2, 5, 59)

    def test_case_insensitive_rdoc(self):
        # scoreMatch*4 + bonusCamel123 + bonusConsecutive*2 = 64+7+8 = 79
        assert exact_match_naive("/AutomatorDocument.icns", "rdoc", case_sensitive=False) == (9, 13, 79)

    def test_delimiter_boundary(self):
        # scoreMatch*4 + bonusBoundaryDelimiter*(firstCharMult+3) = 64+45 = 109
        assert exact_match_naive("/man1/zshcompctl.1", "zshc", case_sensitive=False) == (6, 10, 109)

    def test_mixed_boundary_delimiter(self):
        # scoreMatch*5 + bonusBoundary*(firstCharMult+3) + bonusBoundaryDelimiter = 80+40+9 = 129
        assert exact_match_naive("/.oh-my-zsh/cache", "zsh/c", case_sensitive=False) == (8, 13, 129)

    def test_empty_pattern(self):
        assert exact_match_naive("foobar", "", case_sensitive=True) == (0, 0, 0)

    def test_empty_pattern_insensitive(self):
        assert exact_match_naive("foobar", "", case_sensitive=False) == (0, 0, 0)


# ═══════════════════════════════════════════════════════════
#  PrefixMatch
# ═══════════════════════════════════════════════════════════

class TestPrefixMatch:

    def test_case_sensitive_mismatch(self):
        assert prefix_match("fooBarbaz", "Foo", case_sensitive=True) == (-1, -1, 0)

    def test_not_prefix(self):
        assert prefix_match("fooBarBaz", "baz", case_sensitive=False) == (-1, -1, 0)

    def test_basic_prefix(self):
        # scoreMatch*3 + boundaryWhite*firstCharMult + boundaryWhite*2 = 48+20+20 = 88
        assert prefix_match("fooBarbaz", "Foo", case_sensitive=False) == (0, 3, 88)

    def test_case_fold(self):
        assert prefix_match("foOBarBaZ", "foo", case_sensitive=False) == (0, 3, 88)

    def test_nonword_prefix(self):
        assert prefix_match("f-oBarbaz", "f-o", case_sensitive=False) == (0, 3, 88)

    def test_leading_whitespace_stripped(self):
        assert prefix_match(" fooBar", "foo", case_sensitive=False) == (1, 4, 88)

    def test_space_in_pattern(self):
        assert prefix_match(" fooBar", " fo", case_sensitive=False) == (0, 3, 88)

    def test_too_short_after_trim(self):
        assert prefix_match("     fo", "foo", case_sensitive=False) == (-1, -1, 0)

    def test_empty_pattern(self):
        assert prefix_match("foobar", "", case_sensitive=True) == (0, 0, 0)


# ═══════════════════════════════════════════════════════════
#  SuffixMatch
# ═══════════════════════════════════════════════════════════

class TestSuffixMatch:

    def test_case_sensitive_mismatch(self):
        assert suffix_match("fooBarbaz", "Baz", case_sensitive=True) == (-1, -1, 0)

    def test_not_suffix(self):
        assert suffix_match("fooBarbaz", "Foo", case_sensitive=False) == (-1, -1, 0)

    def test_basic_suffix(self):
        # scoreMatch*3 + bonusConsecutive*2 = 48+8 = 56
        assert suffix_match("fooBarbaz", "baz", case_sensitive=False) == (6, 9, 56)

    def test_camel_suffix(self):
        # (scoreMatch+bonusCamel123)*3 + bonusCamel123*(firstCharMult-1) = 69+7 = 76
        assert suffix_match("fooBarBaZ", "baz", case_sensitive=False) == (6, 9, 76)

    def test_trailing_whitespace_stripped(self):
        assert suffix_match("fooBarbaz ", "baz", case_sensitive=False) == (6, 9, 56)

    def test_trailing_whitespace_pattern_ends_space(self):
        # scoreMatch*4 + bonusConsecutive*2 + bonusBoundaryWhite = 64+8+10 = 82
        assert suffix_match("fooBarbaz ", "baz ", case_sensitive=False) == (6, 10, 82)

    def test_empty_pattern(self):
        assert suffix_match("foobar", "", case_sensitive=True) == (6, 6, 0)

    def test_empty_pattern_insensitive(self):
        assert suffix_match("foobar", "", case_sensitive=False) == (6, 6, 0)


# ═══════════════════════════════════════════════════════════
#  EqualMatch
# ═══════════════════════════════════════════════════════════

class TestEqualMatch:

    def test_exact_match(self):
        # (16+10)*9 + 10 = 244
        assert equal_match("fooBarbaz", "fooBarbaz", case_sensitive=False) == (0, 9, 244)

    def test_case_sensitive_mismatch(self):
        assert equal_match("fooBarbaz", "FooBarbaz", case_sensitive=True) == (-1, -1, 0)

    def test_case_insensitive_match(self):
        assert equal_match("fooBarbaz", "FooBarbaz", case_sensitive=False) == (0, 9, 244)

    def test_whitespace_stripped(self):
        # (16+10)*3 + 10 = 88
        assert equal_match("  foo  ", "foo", case_sensitive=False) == (2, 5, 88)

    def test_empty_pattern(self):
        assert equal_match("foobar", "", case_sensitive=False) == (-1, -1, 0)

    def test_length_mismatch(self):
        assert equal_match("foo", "foobar", case_sensitive=False) == (-1, -1, 0)

    def test_no_match(self):
        assert equal_match("foo", "bar", case_sensitive=False) == (-1, -1, 0)

    def test_single_char(self):
        # (16+10)*1 + 10 = 36
        assert equal_match("x", "x", case_sensitive=True) == (0, 1, 36)


# ═══════════════════════════════════════════════════════════
#  Cross-type empty pattern consistency
# ═══════════════════════════════════════════════════════════

class TestEmptyPatternCrossType:
    """Each match type handles empty pattern differently."""

    def test_fuzzy_empty(self):
        assert fuzzy_match_v2("test", "", case_sensitive=False) == (0, 0, 0)

    def test_exact_empty(self):
        assert exact_match_naive("test", "", case_sensitive=False) == (0, 0, 0)

    def test_prefix_empty(self):
        assert prefix_match("test", "", case_sensitive=False) == (0, 0, 0)

    def test_suffix_empty(self):
        # Suffix with empty pattern returns (len, len, 0)
        assert suffix_match("test", "", case_sensitive=False) == (4, 4, 0)

    def test_equal_empty(self):
        # Equal with empty pattern returns (-1, -1, 0)
        assert equal_match("test", "", case_sensitive=False) == (-1, -1, 0)
