
import subprocess
import json
import pytest


def run_format(message: str, locale: str, values: dict) -> str:
    """Run the ICU MessageFormat formatter via CLI and return the output."""
    result = subprocess.run(
        ["node", "/app/dist/index.js", message, locale, json.dumps(values)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Node process failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Basic formatting
# ---------------------------------------------------------------------------

class TestBasicFormatting:
    def test_simple_argument(self):
        assert run_format("Hello, {name}!", "en", {"name": "World"}) == "Hello, World!"

    def test_multiple_arguments(self):
        msg = "{first} {last} is {age} years old."
        result = run_format(msg, "en", {"first": "John", "last": "Doe", "age": 30})
        assert result == "John Doe is 30 years old."

    def test_plain_text(self):
        assert run_format("Plain text message.", "en", {}) == "Plain text message."

    def test_falsy_false_and_null(self):
        assert run_format("{a}{b}", "en", {"a": False, "b": None}) == ""

    def test_zero_not_falsy(self):
        assert run_format("I am {age} years old.", "en", {"age": 0}) == "I am 0 years old."

    def test_apostrophe_literal(self):
        assert run_format("Peter's friend", "en", {}) == "Peter's friend"

    def test_double_apostrophe(self):
        assert run_format("It''s a test", "en", {}) == "It's a test"

    def test_quoted_brace(self):
        assert run_format("Use '{' and '}' for braces", "en", {}) == "Use { and } for braces"


# ---------------------------------------------------------------------------
# English cardinal plural
# ---------------------------------------------------------------------------

class TestPluralEnglish:
    MSG = "{count, plural, one {# item} other {# items}}"

    def test_one(self):
        assert run_format(self.MSG, "en", {"count": 1}) == "1 item"

    def test_other(self):
        assert run_format(self.MSG, "en", {"count": 5}) == "5 items"

    def test_zero_is_other(self):
        assert run_format(self.MSG, "en", {"count": 0}) == "0 items"


# ---------------------------------------------------------------------------
# Arabic cardinal plural (6 categories)
# ---------------------------------------------------------------------------

class TestPluralArabic:
    MSG = "{n, plural, zero {zero} one {one} two {two} few {few} many {many} other {other}}"

    def test_zero(self):
        assert run_format(self.MSG, "ar", {"n": 0}) == "zero"

    def test_one(self):
        assert run_format(self.MSG, "ar", {"n": 1}) == "one"

    def test_two(self):
        assert run_format(self.MSG, "ar", {"n": 2}) == "two"

    def test_few_5(self):
        assert run_format(self.MSG, "ar", {"n": 5}) == "few"

    def test_few_10(self):
        assert run_format(self.MSG, "ar", {"n": 10}) == "few"

    def test_few_103(self):
        assert run_format(self.MSG, "ar", {"n": 103}) == "few"

    def test_few_210(self):
        assert run_format(self.MSG, "ar", {"n": 210}) == "few"

    def test_many_11(self):
        assert run_format(self.MSG, "ar", {"n": 11}) == "many"

    def test_many_20(self):
        assert run_format(self.MSG, "ar", {"n": 20}) == "many"

    def test_many_99(self):
        assert run_format(self.MSG, "ar", {"n": 99}) == "many"

    def test_many_111(self):
        assert run_format(self.MSG, "ar", {"n": 111}) == "many"

    def test_other_100(self):
        assert run_format(self.MSG, "ar", {"n": 100}) == "other"

    def test_other_200(self):
        assert run_format(self.MSG, "ar", {"n": 200}) == "other"


# ---------------------------------------------------------------------------
# Welsh cardinal plural (specific values)
# ---------------------------------------------------------------------------

class TestPluralWelsh:
    MSG = "{n, plural, zero {zero} one {one} two {two} few {few} many {many} other {other}}"

    def test_zero(self):
        assert run_format(self.MSG, "cy", {"n": 0}) == "zero"

    def test_one(self):
        assert run_format(self.MSG, "cy", {"n": 1}) == "one"

    def test_two(self):
        assert run_format(self.MSG, "cy", {"n": 2}) == "two"

    def test_few(self):
        assert run_format(self.MSG, "cy", {"n": 3}) == "few"

    def test_many(self):
        assert run_format(self.MSG, "cy", {"n": 6}) == "many"

    def test_other_4(self):
        assert run_format(self.MSG, "cy", {"n": 4}) == "other"

    def test_other_5(self):
        assert run_format(self.MSG, "cy", {"n": 5}) == "other"

    def test_other_7(self):
        assert run_format(self.MSG, "cy", {"n": 7}) == "other"

    def test_other_100(self):
        assert run_format(self.MSG, "cy", {"n": 100}) == "other"


# ---------------------------------------------------------------------------
# Russian cardinal plural (modular with 11-14 exception)
# ---------------------------------------------------------------------------

class TestPluralRussian:
    MSG = "{n, plural, one {one} few {few} many {many} other {other}}"

    def test_1_one(self):
        assert run_format(self.MSG, "ru", {"n": 1}) == "one"

    def test_21_one(self):
        assert run_format(self.MSG, "ru", {"n": 21}) == "one"

    def test_31_one(self):
        assert run_format(self.MSG, "ru", {"n": 31}) == "one"

    def test_101_one(self):
        assert run_format(self.MSG, "ru", {"n": 101}) == "one"

    def test_2_few(self):
        assert run_format(self.MSG, "ru", {"n": 2}) == "few"

    def test_3_few(self):
        assert run_format(self.MSG, "ru", {"n": 3}) == "few"

    def test_4_few(self):
        assert run_format(self.MSG, "ru", {"n": 4}) == "few"

    def test_22_few(self):
        assert run_format(self.MSG, "ru", {"n": 22}) == "few"

    def test_34_few(self):
        assert run_format(self.MSG, "ru", {"n": 34}) == "few"

    def test_0_many(self):
        assert run_format(self.MSG, "ru", {"n": 0}) == "many"

    def test_5_many(self):
        assert run_format(self.MSG, "ru", {"n": 5}) == "many"

    def test_10_many(self):
        assert run_format(self.MSG, "ru", {"n": 10}) == "many"

    def test_11_many(self):
        assert run_format(self.MSG, "ru", {"n": 11}) == "many"

    def test_12_many(self):
        assert run_format(self.MSG, "ru", {"n": 12}) == "many"

    def test_14_many(self):
        assert run_format(self.MSG, "ru", {"n": 14}) == "many"

    def test_19_many(self):
        assert run_format(self.MSG, "ru", {"n": 19}) == "many"

    def test_111_many(self):
        assert run_format(self.MSG, "ru", {"n": 111}) == "many"

    def test_112_many(self):
        assert run_format(self.MSG, "ru", {"n": 112}) == "many"


# ---------------------------------------------------------------------------
# Portuguese cardinal plural (0 is singular)
# ---------------------------------------------------------------------------

class TestPluralPortuguese:
    MSG = "{n, plural, one {one} other {other}}"

    def test_zero_is_one(self):
        assert run_format(self.MSG, "pt", {"n": 0}) == "one"

    def test_one_is_one(self):
        assert run_format(self.MSG, "pt", {"n": 1}) == "one"

    def test_two_is_other(self):
        assert run_format(self.MSG, "pt", {"n": 2}) == "other"

    def test_100_is_other(self):
        assert run_format(self.MSG, "pt", {"n": 100}) == "other"


# ---------------------------------------------------------------------------
# Polish cardinal plural (complex few/many)
# ---------------------------------------------------------------------------

class TestPluralPolish:
    MSG = "{n, plural, one {one} few {few} many {many} other {other}}"

    def test_1_one(self):
        assert run_format(self.MSG, "pl", {"n": 1}) == "one"

    def test_2_few(self):
        assert run_format(self.MSG, "pl", {"n": 2}) == "few"

    def test_3_few(self):
        assert run_format(self.MSG, "pl", {"n": 3}) == "few"

    def test_4_few(self):
        assert run_format(self.MSG, "pl", {"n": 4}) == "few"

    def test_22_few(self):
        assert run_format(self.MSG, "pl", {"n": 22}) == "few"

    def test_24_few(self):
        assert run_format(self.MSG, "pl", {"n": 24}) == "few"

    def test_0_many(self):
        assert run_format(self.MSG, "pl", {"n": 0}) == "many"

    def test_5_many(self):
        assert run_format(self.MSG, "pl", {"n": 5}) == "many"

    def test_10_many(self):
        assert run_format(self.MSG, "pl", {"n": 10}) == "many"

    def test_11_many(self):
        assert run_format(self.MSG, "pl", {"n": 11}) == "many"

    def test_12_many(self):
        assert run_format(self.MSG, "pl", {"n": 12}) == "many"

    def test_14_many(self):
        assert run_format(self.MSG, "pl", {"n": 14}) == "many"

    def test_112_many(self):
        assert run_format(self.MSG, "pl", {"n": 112}) == "many"

    def test_20_many(self):
        assert run_format(self.MSG, "pl", {"n": 20}) == "many"


# ---------------------------------------------------------------------------
# French cardinal plural (0 and 1 are singular)
# ---------------------------------------------------------------------------

class TestPluralFrench:
    MSG = "{n, plural, one {one} other {other}}"

    def test_zero_is_one(self):
        assert run_format(self.MSG, "fr", {"n": 0}) == "one"

    def test_one_is_one(self):
        assert run_format(self.MSG, "fr", {"n": 1}) == "one"

    def test_two_is_other(self):
        assert run_format(self.MSG, "fr", {"n": 2}) == "other"


# ---------------------------------------------------------------------------
# Japanese cardinal plural (no distinction)
# ---------------------------------------------------------------------------

class TestPluralJapanese:
    MSG = "{n, plural, one {one} other {other}}"

    def test_zero_is_other(self):
        assert run_format(self.MSG, "ja", {"n": 0}) == "other"

    def test_one_is_other(self):
        assert run_format(self.MSG, "ja", {"n": 1}) == "other"

    def test_two_is_other(self):
        assert run_format(self.MSG, "ja", {"n": 2}) == "other"


# ---------------------------------------------------------------------------
# Exact match priority
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_exact_match_over_rule(self):
        msg = "{n, plural, =0 {none} =1 {exactly one} one {about one} other {many}}"
        assert run_format(msg, "en", {"n": 1}) == "exactly one"

    def test_exact_zero(self):
        msg = "{n, plural, =0 {no items} one {# item} other {# items}}"
        assert run_format(msg, "en", {"n": 0}) == "no items"

    def test_fallthrough_to_rule(self):
        msg = "{n, plural, =0 {none} one {one} other {many}}"
        assert run_format(msg, "en", {"n": 1}) == "one"
        assert run_format(msg, "en", {"n": 5}) == "many"


# ---------------------------------------------------------------------------
# Offset and hash replacement
# ---------------------------------------------------------------------------

class TestOffset:
    MSG = "{n, plural, offset:1 =0 {nobody} =1 {just {host}} other {{host} and # others}}"

    def test_exact_zero(self):
        assert run_format(self.MSG, "en", {"n": 0, "host": "Alice"}) == "nobody"

    def test_exact_one(self):
        assert run_format(self.MSG, "en", {"n": 1, "host": "Alice"}) == "just Alice"

    def test_offset_hash_3(self):
        assert (
            run_format(self.MSG, "en", {"n": 3, "host": "Alice"})
            == "Alice and 2 others"
        )

    def test_offset_hash_4(self):
        assert (
            run_format(self.MSG, "en", {"n": 4, "host": "Alice"})
            == "Alice and 3 others"
        )

    def test_offset_hash_10(self):
        assert (
            run_format(self.MSG, "en", {"n": 10, "host": "Alice"})
            == "Alice and 9 others"
        )


# ---------------------------------------------------------------------------
# Select
# ---------------------------------------------------------------------------

class TestSelect:
    MSG = "{gender, select, female {She} male {He} other {They}} went to {city}."

    def test_female(self):
        assert (
            run_format(self.MSG, "en", {"gender": "female", "city": "Paris"})
            == "She went to Paris."
        )

    def test_male(self):
        assert (
            run_format(self.MSG, "en", {"gender": "male", "city": "Paris"})
            == "He went to Paris."
        )

    def test_fallback(self):
        assert (
            run_format(self.MSG, "en", {"gender": "unknown", "city": "Paris"})
            == "They went to Paris."
        )


# ---------------------------------------------------------------------------
# English selectordinal
# ---------------------------------------------------------------------------

class TestSelectordinal:
    MSG = "This is the {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}} time."

    def test_1st(self):
        assert run_format(self.MSG, "en", {"n": 1}) == "This is the 1st time."

    def test_2nd(self):
        assert run_format(self.MSG, "en", {"n": 2}) == "This is the 2nd time."

    def test_3rd(self):
        assert run_format(self.MSG, "en", {"n": 3}) == "This is the 3rd time."

    def test_4th(self):
        assert run_format(self.MSG, "en", {"n": 4}) == "This is the 4th time."

    def test_11th(self):
        assert run_format(self.MSG, "en", {"n": 11}) == "This is the 11th time."

    def test_12th(self):
        assert run_format(self.MSG, "en", {"n": 12}) == "This is the 12th time."

    def test_13th(self):
        assert run_format(self.MSG, "en", {"n": 13}) == "This is the 13th time."

    def test_21st(self):
        assert run_format(self.MSG, "en", {"n": 21}) == "This is the 21st time."

    def test_22nd(self):
        assert run_format(self.MSG, "en", {"n": 22}) == "This is the 22nd time."

    def test_23rd(self):
        assert run_format(self.MSG, "en", {"n": 23}) == "This is the 23rd time."

    def test_111th(self):
        assert run_format(self.MSG, "en", {"n": 111}) == "This is the 111th time."

    def test_112th(self):
        assert run_format(self.MSG, "en", {"n": 112}) == "This is the 112th time."

    def test_113th(self):
        assert run_format(self.MSG, "en", {"n": 113}) == "This is the 113th time."


# ---------------------------------------------------------------------------
# Nested constructs
# ---------------------------------------------------------------------------

class TestNestedConstructs:
    def test_plural_in_select(self):
        msg = (
            "{gender, select, "
            "female {She has {count, plural, one {# cat} other {# cats}}} "
            "other {They have {count, plural, one {# cat} other {# cats}}}}"
        )
        assert run_format(msg, "en", {"gender": "female", "count": 1}) == "She has 1 cat"
        assert run_format(msg, "en", {"gender": "male", "count": 5}) == "They have 5 cats"

    def test_select_in_plural(self):
        msg = (
            "{count, plural, "
            "one {{gender, select, female {She} other {He}} has # cat} "
            "other {{gender, select, female {She} other {He}} has # cats}}"
        )
        assert run_format(msg, "en", {"count": 1, "gender": "female"}) == "She has 1 cat"
        assert run_format(msg, "en", {"count": 3, "gender": "male"}) == "He has 3 cats"

    def test_deeply_nested(self):
        msg = (
            "{g, select, "
            "female {{n, plural, =1 {She has one} other {She has {n}}}} "
            "other {{n, plural, =1 {He has one} other {He has {n}}}}}"
        )
        assert run_format(msg, "en", {"g": "female", "n": 1}) == "She has one"
        assert run_format(msg, "en", {"g": "male", "n": 42}) == "He has 42"

    def test_hash_scoping_in_nested_select(self):
        """Hash inside select options within plural is literal (not PoundElement)."""
        msg = (
            "{count, plural, "
            "one {{unit, select, hour {# hour} other {# unit}}} "
            "other {{unit, select, hour {# hours} other {# units}}}}"
        )
        assert run_format(msg, "en", {"count": 1, "unit": "hour"}) == "# hour"
        assert run_format(msg, "en", {"count": 3, "unit": "hour"}) == "# hours"

    def test_hash_works_in_direct_plural_with_surrounding_select(self):
        """Hash works when directly in plural option alongside select."""
        msg = (
            "{count, plural, "
            "one {# {unit, select, hour {hour} other {unit}}} "
            "other {# {unit, select, hour {hours} other {units}}}}"
        )
        assert run_format(msg, "en", {"count": 1, "unit": "hour"}) == "1 hour"
        assert run_format(msg, "en", {"count": 3, "unit": "hour"}) == "3 hours"


# ---------------------------------------------------------------------------
# Prototype pollution safety
# ---------------------------------------------------------------------------

class TestPrototypeSafety:
    def test_constructor(self):
        msg = "{x, select, constructor {C} other {O}}"
        assert run_format(msg, "en", {"x": "constructor"}) == "C"

    def test_proto(self):
        msg = "{x, select, __proto__ {P} other {O}}"
        assert run_format(msg, "en", {"x": "__proto__"}) == "P"

    def test_toString(self):
        msg = "{x, select, toString {T} other {O}}"
        assert run_format(msg, "en", {"x": "toString"}) == "T"

    def test_valueOf(self):
        msg = "{x, select, valueOf {V} other {O}}"
        assert run_format(msg, "en", {"x": "valueOf"}) == "V"

    def test_hasOwnProperty(self):
        msg = "{x, select, hasOwnProperty {H} other {O}}"
        assert run_format(msg, "en", {"x": "hasOwnProperty"}) == "H"


# ---------------------------------------------------------------------------
# Quoted hash in plural context
# ---------------------------------------------------------------------------

class TestQuotedHash:
    def test_quoted_hash_preserved(self):
        msg = "{count, plural, one {You have '#' item} other {You have '#' items}}"
        assert run_format(msg, "en", {"count": 1}) == "You have # item"
        assert run_format(msg, "en", {"count": 5}) == "You have # items"


# ---------------------------------------------------------------------------
# Russian complex with hash and exact match
# ---------------------------------------------------------------------------

class TestRussianComplex:
    MSG = "{n, plural, =1 {Одна компания} one {# компания} few {# компании} many {# компаний} other {# компаний}}"

    def test_exact_1(self):
        assert run_format(self.MSG, "ru", {"n": 1}) == "Одна компания"

    def test_21_one(self):
        assert run_format(self.MSG, "ru", {"n": 21}) == "21 компания"

    def test_2_few(self):
        assert run_format(self.MSG, "ru", {"n": 2}) == "2 компании"

    def test_5_many(self):
        assert run_format(self.MSG, "ru", {"n": 5}) == "5 компаний"

    def test_11_many(self):
        assert run_format(self.MSG, "ru", {"n": 11}) == "11 компаний"

    def test_0_many(self):
        assert run_format(self.MSG, "ru", {"n": 0}) == "0 компаний"


# ---------------------------------------------------------------------------
# CLDR evaluator edge cases (modulus, ranges, inequality interactions)
# ---------------------------------------------------------------------------

class TestCLDREdgeCases:
    """Tests that specifically exercise complex CLDR expression evaluation."""

    def test_russian_1001_one(self):
        """1001 % 10 = 1, 1001 % 100 = 1 (not 11), so 'one'."""
        msg = "{n, plural, one {one} few {few} many {many} other {other}}"
        assert run_format(msg, "ru", {"n": 1001}) == "one"

    def test_russian_1002_few(self):
        """1002 % 10 = 2, 1002 % 100 = 2 (not in 12..14), so 'few'."""
        msg = "{n, plural, one {one} few {few} many {many} other {other}}"
        assert run_format(msg, "ru", {"n": 1002}) == "few"

    def test_polish_102_few(self):
        """102 % 10 = 2, 102 % 100 = 2 (not in 12..14), so 'few'."""
        msg = "{n, plural, one {one} few {few} many {many} other {other}}"
        assert run_format(msg, "pl", {"n": 102}) == "few"

    def test_polish_1012_many(self):
        """1012 % 100 = 12, which is in 12..14, so 'many'."""
        msg = "{n, plural, one {one} few {few} many {many} other {other}}"
        assert run_format(msg, "pl", {"n": 1012}) == "many"

    def test_arabic_110_few(self):
        """110 % 100 = 10, which is in 3..10, so 'few'."""
        msg = "{n, plural, zero {zero} one {one} two {two} few {few} many {many} other {other}}"
        assert run_format(msg, "ar", {"n": 110}) == "few"

    def test_arabic_1011_many(self):
        """1011 % 100 = 11, which is in 11..99, so 'many'."""
        msg = "{n, plural, zero {zero} one {one} two {two} few {few} many {many} other {other}}"
        assert run_format(msg, "ar", {"n": 1011}) == "many"

    def test_english_ordinal_101st(self):
        """101 % 10 = 1, 101 % 100 = 1 (not 11), so ordinal 'one' -> st."""
        msg = "The {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}."
        assert run_format(msg, "en", {"n": 101}) == "The 101st."

    def test_english_ordinal_102nd(self):
        """102 % 10 = 2, 102 % 100 = 2 (not 12), so ordinal 'two' -> nd."""
        msg = "The {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}."
        assert run_format(msg, "en", {"n": 102}) == "The 102nd."

    def test_english_ordinal_103rd(self):
        """103 % 10 = 3, 103 % 100 = 3 (not 13), so ordinal 'few' -> rd."""
        msg = "The {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}."
        assert run_format(msg, "en", {"n": 103}) == "The 103rd."

    def test_english_ordinal_1011th(self):
        """1011 % 100 = 11, so != check matches -> ordinal 'other' -> th."""
        msg = "The {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}."
        assert run_format(msg, "en", {"n": 1011}) == "The 1,011th."


# ---------------------------------------------------------------------------
# Combined multi-feature patterns
# ---------------------------------------------------------------------------

class TestCombinedPatterns:
    """Tests combining offset, hash, plural rules, and nesting."""

    def test_polish_offset_with_hash(self):
        """Polish plurals with offset require correct evaluator + formatter interaction."""
        msg = "{n, plural, offset:1 =0 {Nikt} =1 {Tylko {host}} one {# osoba i {host}} few {# osoby i {host}} many {# osob i {host}} other {# osob i {host}}}"
        assert run_format(msg, "pl", {"n": 0, "host": "Ania"}) == "Nikt"
        assert run_format(msg, "pl", {"n": 1, "host": "Ania"}) == "Tylko Ania"
        # n=2, offset 1 -> offsetVal=1 -> pl 'one' (i=1 and v=0)
        assert run_format(msg, "pl", {"n": 2, "host": "Ania"}) == "1 osoba i Ania"
        # n=4, offset 1 -> offsetVal=3 -> pl 'few' (3 % 10 = 3, in 2..4)
        assert run_format(msg, "pl", {"n": 4, "host": "Ania"}) == "3 osoby i Ania"
        # n=6, offset 1 -> offsetVal=5 -> pl 'many' (5 % 10 = 5, in 5..9)
        assert run_format(msg, "pl", {"n": 6, "host": "Ania"}) == "5 osob i Ania"

    def test_arabic_nested_with_select(self):
        """Arabic cardinals inside select nesting."""
        msg = (
            "{gender, select, "
            "male {{n, plural, zero {la shay} one {wahid} two {ithnan} few {# qalil} many {# kathir} other {# other}}} "
            "other {{n, plural, one {wahid} other {# items}}}}"
        )
        assert run_format(msg, "ar", {"gender": "male", "n": 0}) == "la shay"
        assert run_format(msg, "ar", {"gender": "male", "n": 5}) == "5 qalil"
        assert run_format(msg, "ar", {"gender": "male", "n": 11}) == "11 kathir"
        assert run_format(msg, "ar", {"gender": "male", "n": 100}) == "100 other"

    def test_russian_exact_match_uses_raw_value(self):
        """Exact match with offset must use raw value, not offset-adjusted."""
        msg = "{n, plural, offset:2 =2 {exactly two} one {# one-ish} few {# few-ish} many {# many-ish} other {# other-ish}}"
        # n=2, rawVal=2, exactKey='=2' matches
        assert run_format(msg, "ru", {"n": 2}) == "exactly two"
        # n=3, rawVal=3, no exact match; offsetVal=1 -> ru 'one'
        assert run_format(msg, "ru", {"n": 3}) == "1 one-ish"
        # n=5, rawVal=5, no exact match; offsetVal=3 -> ru 'few' (3 % 10 = 3, in 2..4)
        assert run_format(msg, "ru", {"n": 5}) == "3 few-ish"
