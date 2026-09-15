"""
Tests for fzf FuzzyMatchV2 scoring algorithm implementation.

All expected values are derived from fzf's algo_test.go test vectors.

"""
import sys
import pytest

sys.path.insert(0, "/app")

from fzf_scorer import (
    Result,
    fuzzy_match_v1,
    fuzzy_match_v2,
    exact_match_naive,
    prefix_match,
    suffix_match,
    equal_match,
    normalize_rune,
    calculate_score,
    bonus_at,
    char_class_of,
    SCORE_MATCH,
    SCORE_GAP_START,
    SCORE_GAP_EXTENSION,
    BONUS_BOUNDARY,
    BONUS_NON_WORD,
    BONUS_CAMEL_123,
    BONUS_CONSECUTIVE,
    BONUS_FIRST_CHAR_MULTIPLIER,
    bonus_boundary_white,
    bonus_boundary_delimiter,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def assert_match(fn, case_sensitive, forward, input_str, pattern, sidx, eidx, expected_score):
    """Mirror of assertMatch from algo_test.go"""
    if not case_sensitive:
        pattern = pattern.lower()
    res, pos = fn(case_sensitive, False, forward, input_str, pattern, True)
    if pos is not None and len(pos) > 0:
        pos_sorted = sorted(pos)
        start = pos_sorted[0]
        end = pos_sorted[-1] + 1
    else:
        start = res.start
        end = res.end
    assert start == sidx, f"start: got {start}, expected {sidx} for ({input_str!r}, {pattern!r})"
    assert end == eidx, f"end: got {end}, expected {eidx} for ({input_str!r}, {pattern!r})"
    assert res.score == expected_score, f"score: got {res.score}, expected {expected_score} for ({input_str!r}, {pattern!r})"


def assert_match_norm(fn, case_sensitive, normalize, forward, input_str, pattern, sidx, eidx, expected_score):
    """Mirror of assertMatch2 from algo_test.go (with normalize flag)"""
    if not case_sensitive:
        pattern = pattern.lower()
    res, pos = fn(case_sensitive, normalize, forward, input_str, pattern, True)
    if pos is not None and len(pos) > 0:
        pos_sorted = sorted(pos)
        start = pos_sorted[0]
        end = pos_sorted[-1] + 1
    else:
        start = res.start
        end = res.end
    assert start == sidx, f"start: got {start}, expected {sidx} for ({input_str!r}, {pattern!r})"
    assert end == eidx, f"end: got {end}, expected {eidx} for ({input_str!r}, {pattern!r})"
    assert res.score == expected_score, f"score: got {res.score}, expected {expected_score} for ({input_str!r}, {pattern!r})"


# ---------------------------------------------------------------------------
# Constants sanity check
# ---------------------------------------------------------------------------

class TestConstants:
    def test_score_match(self):
        assert SCORE_MATCH == 16

    def test_score_gap_start(self):
        assert SCORE_GAP_START == -3

    def test_score_gap_extension(self):
        assert SCORE_GAP_EXTENSION == -1

    def test_bonus_boundary(self):
        assert BONUS_BOUNDARY == 8

    def test_bonus_camel123(self):
        assert BONUS_CAMEL_123 == 7

    def test_bonus_consecutive(self):
        assert BONUS_CONSECUTIVE == 4

    def test_bonus_boundary_white(self):
        assert bonus_boundary_white == 10

    def test_bonus_boundary_delimiter(self):
        assert bonus_boundary_delimiter == 9


# ---------------------------------------------------------------------------
# Character classification
# ---------------------------------------------------------------------------

class TestCharClass:
    def test_lower(self):
        assert char_class_of('a') == 3  # CHAR_LOWER

    def test_upper(self):
        assert char_class_of('A') == 4  # CHAR_UPPER

    def test_digit(self):
        assert char_class_of('0') == 6  # CHAR_NUMBER

    def test_space(self):
        assert char_class_of(' ') == 0  # CHAR_WHITE

    def test_slash(self):
        assert char_class_of('/') == 2  # CHAR_DELIMITER

    def test_dot(self):
        assert char_class_of('.') == 1  # CHAR_NON_WORD

    def test_bonus_at_start(self):
        assert bonus_at("foo", 0) == bonus_boundary_white


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_normalize_accented(self):
        assert normalize_rune('\u00f3') == 'o'  # ó -> o

    def test_normalize_cedilla(self):
        assert normalize_rune('\u00e7') == 'c'  # ç -> c

    def test_normalize_plain(self):
        assert normalize_rune('a') == 'a'


# ---------------------------------------------------------------------------
# FuzzyMatch (V1 and V2) — case-insensitive, both directions
# ---------------------------------------------------------------------------

class TestFuzzyMatchCaseInsensitive:
    """Tests from TestFuzzyMatch in algo_test.go — case_sensitive=False"""

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_camel_case_oBZ(self, fn, forward):
        assert_match(fn, False, forward, "fooBarbaz1", "oBZ", 2, 9, 49)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_word_boundary_fbb(self, fn, forward):
        assert_match(fn, False, forward, "foo bar baz", "fbb", 0, 9, 78)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_automator_rdoc(self, fn, forward):
        assert_match(fn, False, forward, "/AutomatorDocument.icns", "rdoc", 9, 13, 79)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_zshcompctl_zshc(self, fn, forward):
        assert_match(fn, False, forward, "/man1/zshcompctl.1", "zshc", 6, 10, 109)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_oh_my_zsh_zshc(self, fn, forward):
        assert_match(fn, False, forward, "/.oh-my-zsh/cache", "zshc", 8, 13, 102)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_vimrc_full(self, fn, forward):
        assert_match(fn, False, forward, ".vimrc", ".vimrc", 0, 6, 166)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_slash_vimrc(self, fn, forward):
        assert_match(fn, False, forward, "/.vimrc", ".vimrc", 1, 7, 159)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_a_vimrc(self, fn, forward):
        assert_match(fn, False, forward, "a.vimrc", ".vimrc", 1, 7, 152)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_digits_12356(self, fn, forward):
        assert_match(fn, False, forward, "ab0123 456", "12356", 3, 10, 88)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_digits_camel_12356(self, fn, forward):
        assert_match(fn, False, forward, "abc123 456", "12356", 3, 10, 108)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_path_fbb(self, fn, forward):
        assert_match(fn, False, forward, "foo/bar/baz", "fbb", 0, 9, 76)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_camel_fbb(self, fn, forward):
        assert_match(fn, False, forward, "fooBarBaz", "fbb", 0, 7, 74)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_mixed_fbb(self, fn, forward):
        assert_match(fn, False, forward, "foo barbaz", "fbb", 0, 8, 69)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_consecutive_foob(self, fn, forward):
        assert_match(fn, False, forward, "fooBar Baz", "foob", 0, 4, 114)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_xfoo_bar(self, fn, forward):
        assert_match(fn, False, forward, "xFoo-Bar Baz", "foo-b", 1, 6, 124)


# ---------------------------------------------------------------------------
# FuzzyMatch — case-sensitive
# ---------------------------------------------------------------------------

class TestFuzzyMatchCaseSensitive:

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_oBz(self, fn, forward):
        assert_match(fn, True, forward, "fooBarbaz", "oBz", 2, 9, 49)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_path_FBB(self, fn, forward):
        assert_match(fn, True, forward, "Foo/Bar/Baz", "FBB", 0, 9, 76)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_camel_FBB(self, fn, forward):
        assert_match(fn, True, forward, "FooBarBaz", "FBB", 0, 7, 74)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_FooB(self, fn, forward):
        assert_match(fn, True, forward, "FooBar Baz", "FooB", 0, 4, 114)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_consecutive_o_ba(self, fn, forward):
        assert_match(fn, True, forward, "foo-bar", "o-ba", 2, 6, 88)


# ---------------------------------------------------------------------------
# FuzzyMatch — non-matches
# ---------------------------------------------------------------------------

class TestFuzzyMatchNonMatch:

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_nonmatch_oBZ(self, fn, forward):
        assert_match(fn, True, forward, "fooBarbaz", "oBZ", -1, -1, 0)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_nonmatch_fbb(self, fn, forward):
        assert_match(fn, True, forward, "Foo Bar Baz", "fbb", -1, -1, 0)

    @pytest.mark.parametrize("fn", [fuzzy_match_v1, fuzzy_match_v2])
    @pytest.mark.parametrize("forward", [True, False])
    def test_pattern_too_long(self, fn, forward):
        assert_match(fn, True, forward, "fooBarbaz", "fooBarbazz", -1, -1, 0)


# ---------------------------------------------------------------------------
# FuzzyMatchV1 backward matching
# ---------------------------------------------------------------------------

class TestFuzzyMatchBackward:
    def test_v1_forward_fb(self):
        assert_match(fuzzy_match_v1, False, True, "foobar fb", "fb", 0, 4, 48)

    def test_v1_backward_fb(self):
        assert_match(fuzzy_match_v1, False, False, "foobar fb", "fb", 7, 9, 62)


# ---------------------------------------------------------------------------
# ExactMatchNaive
# ---------------------------------------------------------------------------

class TestExactMatchNaive:

    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_nonmatch(self, forward):
        assert_match(exact_match_naive, True, forward, "fooBarbaz", "oBA", -1, -1, 0)

    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_too_long(self, forward):
        assert_match(exact_match_naive, True, forward, "fooBarbaz", "fooBarbazz", -1, -1, 0)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_oBA(self, forward):
        assert_match(exact_match_naive, False, forward, "fooBarbaz", "oBA", 2, 5, 59)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_rdoc(self, forward):
        assert_match(exact_match_naive, False, forward, "/AutomatorDocument.icns", "rdoc", 9, 13, 79)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_zshc(self, forward):
        assert_match(exact_match_naive, False, forward, "/man1/zshcompctl.1", "zshc", 6, 10, 109)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_zsh_cache(self, forward):
        assert_match(exact_match_naive, False, forward, "/.oh-my-zsh/cache", "zsh/c", 8, 13, 129)


class TestExactMatchNaiveBackward:
    def test_forward_oo(self):
        assert_match(exact_match_naive, False, True, "foobar foob", "oo", 1, 3, 36)

    def test_backward_oo(self):
        assert_match(exact_match_naive, False, False, "foobar foob", "oo", 8, 10, 36)


# ---------------------------------------------------------------------------
# PrefixMatch
# ---------------------------------------------------------------------------

class TestPrefixMatch:

    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_nonmatch(self, forward):
        assert_match(prefix_match, True, forward, "fooBarbaz", "Foo", -1, -1, 0)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_wrong_suffix(self, forward):
        assert_match(prefix_match, False, forward, "fooBarBaz", "baz", -1, -1, 0)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_Foo(self, forward):
        assert_match(prefix_match, False, forward, "fooBarbaz", "Foo", 0, 3, 88)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_mixed_case(self, forward):
        assert_match(prefix_match, False, forward, "foOBarBaZ", "foo", 0, 3, 88)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_dash(self, forward):
        assert_match(prefix_match, False, forward, "f-oBarbaz", "f-o", 0, 3, 88)

    @pytest.mark.parametrize("forward", [True, False])
    def test_leading_space(self, forward):
        assert_match(prefix_match, False, forward, " fooBar", "foo", 1, 4, 88)

    @pytest.mark.parametrize("forward", [True, False])
    def test_pattern_with_space(self, forward):
        assert_match(prefix_match, False, forward, " fooBar", " fo", 0, 3, 88)

    @pytest.mark.parametrize("forward", [True, False])
    def test_too_short(self, forward):
        assert_match(prefix_match, False, forward, "     fo", "foo", -1, -1, 0)


# ---------------------------------------------------------------------------
# SuffixMatch
# ---------------------------------------------------------------------------

class TestSuffixMatch:

    @pytest.mark.parametrize("forward", [True, False])
    def test_cs_nonmatch(self, forward):
        assert_match(suffix_match, True, forward, "fooBarbaz", "Baz", -1, -1, 0)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_wrong_prefix(self, forward):
        assert_match(suffix_match, False, forward, "fooBarbaz", "Foo", -1, -1, 0)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_baz(self, forward):
        assert_match(suffix_match, False, forward, "fooBarbaz", "baz", 6, 9, 56)

    @pytest.mark.parametrize("forward", [True, False])
    def test_ci_camel_baz(self, forward):
        assert_match(suffix_match, False, forward, "fooBarBaZ", "baz", 6, 9, 76)

    @pytest.mark.parametrize("forward", [True, False])
    def test_trailing_space(self, forward):
        assert_match(suffix_match, False, forward, "fooBarbaz ", "baz", 6, 9, 56)

    @pytest.mark.parametrize("forward", [True, False])
    def test_pattern_with_space(self, forward):
        assert_match(suffix_match, False, forward, "fooBarbaz ", "baz ", 6, 10, 82)


# ---------------------------------------------------------------------------
# Empty pattern
# ---------------------------------------------------------------------------

class TestEmptyPattern:

    @pytest.mark.parametrize("forward", [True, False])
    def test_fuzzy_v1_empty(self, forward):
        res, _ = fuzzy_match_v1(True, False, forward, "foobar", "", True)
        assert res.start == 0 and res.end == 0 and res.score == 0

    @pytest.mark.parametrize("forward", [True, False])
    def test_fuzzy_v2_empty(self, forward):
        res, _ = fuzzy_match_v2(True, False, forward, "foobar", "", True)
        assert res.start == 0 and res.end == 0 and res.score == 0

    @pytest.mark.parametrize("forward", [True, False])
    def test_exact_empty(self, forward):
        res, _ = exact_match_naive(True, False, forward, "foobar", "", True)
        assert res.start == 0 and res.end == 0 and res.score == 0

    @pytest.mark.parametrize("forward", [True, False])
    def test_prefix_empty(self, forward):
        res, _ = prefix_match(True, False, forward, "foobar", "", True)
        assert res.start == 0 and res.end == 0 and res.score == 0

    @pytest.mark.parametrize("forward", [True, False])
    def test_suffix_empty(self, forward):
        res, _ = suffix_match(True, False, forward, "foobar", "", True)
        assert res.start == 6 and res.end == 6 and res.score == 0


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalization:

    def test_so_prefix(self):
        for fn in [fuzzy_match_v1, fuzzy_match_v2, prefix_match, exact_match_naive]:
            assert_match_norm(fn, False, True, True, "S\u00f3 Dan\u00e7o Samba", "So", 0, 2, 62)

    def test_sodc_fuzzy(self):
        for fn in [fuzzy_match_v1, fuzzy_match_v2]:
            assert_match_norm(fn, False, True, True, "S\u00f3 Dan\u00e7o Samba", "sodc", 0, 7, 97)

    def test_danco_all(self):
        for fn in [fuzzy_match_v1, fuzzy_match_v2, prefix_match, suffix_match, exact_match_naive, equal_match]:
            assert_match_norm(fn, False, True, True, "Dan\u00e7o", "danco", 0, 5, 140)


# ---------------------------------------------------------------------------
# Long string test (V2 fallback to V1)
# ---------------------------------------------------------------------------

class TestLongString:

    def test_long_v2(self):
        text = "x" * 65535 + "z" + "x"
        res, _ = fuzzy_match_v2(True, False, True, text, "zx", True)
        assert res.start == 65535
        assert res.end == 65537
        expected = SCORE_MATCH * 2 + BONUS_CONSECUTIVE
        assert res.score == expected


# ---------------------------------------------------------------------------
# calculate_score direct tests
# ---------------------------------------------------------------------------

class TestCalculateScore:

    def test_simple_consecutive(self):
        # "foobar" matching "foo" at [0,3)
        score, pos = calculate_score(False, False, "foobar", "foo", 0, 3, True)
        # first char: SCORE_MATCH + bonus_boundary_white * multiplier = 16 + 10*2 = 36
        # second char: SCORE_MATCH + max(bonus, firstBonus, BONUS_CONSECUTIVE)
        #   bonus for o after o = 0, firstBonus = 10, consecutive = 4
        #   -> max(0, 10, 4) = 10 -> 16 + 10 = 26
        # third char: same -> 16 + 10 = 26
        # total = 36 + 26 + 26 = 88
        assert score == 88
        assert pos == [0, 1, 2]

    def test_gap_penalty(self):
        # "f__b" matching "fb" at [0,4)
        # f: 16 + 10*2 = 36 (boundary white, first char multiplier)
        # _: gap start = -3 -> 33
        # _: gap extension = -1 -> 32
        # b: prev is CHAR_NON_WORD, cur is CHAR_LOWER -> BONUS_BOUNDARY=8
        #    16 + 8 = 24 -> total 56
        score, _ = calculate_score(False, False, "f__b", "fb", 0, 4, False)
        assert score == 56
