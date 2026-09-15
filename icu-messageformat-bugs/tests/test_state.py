
import subprocess
import json
import pytest


def run_formatter(pattern: str, locale: str, values: dict, timeout: int = 30) -> str:
    """Run the ICU MessageFormat CLI and return the formatted output."""
    input_data = json.dumps({"pattern": pattern, "locale": locale, "values": values})
    result = subprocess.run(
        ["npx", "tsx", "/app/src/index.ts"],
        input=input_data,
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"CLI exited with code {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Basic formatting — should pass even with all bugs present
# ---------------------------------------------------------------------------

class TestBasicFormatting:
    def test_plain_text(self):
        assert run_formatter("Hello, World!", "en", {}) == "Hello, World!"

    def test_simple_argument(self):
        assert run_formatter("Hello {name}", "en", {"name": "World"}) == "Hello World"

    def test_multiple_arguments(self):
        result = run_formatter(
            "My name is {FIRST} {LAST}.", "en", {"FIRST": "Anthony", "LAST": "Pipkin"}
        )
        assert result == "My name is Anthony Pipkin."

    def test_numeric_argument_as_string(self):
        assert run_formatter("I am {age} years old.", "en", {"age": 25}) == "I am 25 years old."

    def test_zero_value(self):
        assert run_formatter("Count: {n}", "en", {"n": 0}) == "Count: 0"


# ---------------------------------------------------------------------------
# Select arguments — should pass with no fixes
# ---------------------------------------------------------------------------

class TestSelect:
    def test_select_male(self):
        p = "{gender, select, male {He} female {She} other {They}}"
        assert run_formatter(p, "en", {"gender": "male"}) == "He"

    def test_select_female(self):
        p = "{gender, select, male {He} female {She} other {They}}"
        assert run_formatter(p, "en", {"gender": "female"}) == "She"

    def test_select_other_fallback(self):
        p = "{gender, select, male {He} female {She} other {They}}"
        assert run_formatter(p, "en", {"gender": "unknown"}) == "They"

    def test_select_with_arguments(self):
        p = "{GENDER, select, female {{NAME} est allee a {CITY}.} other {{NAME} est alle a {CITY}.}}"
        result = run_formatter(p, "fr", {"NAME": "Jenny", "CITY": "Paris", "GENDER": "female"})
        assert result == "Jenny est allee a Paris."


# ---------------------------------------------------------------------------
# Plural with exact match (=N) — bypasses evaluator, should pass
# ---------------------------------------------------------------------------

class TestPluralExactMatch:
    def test_exact_zero(self):
        p = "{count, plural, =0 {No items} =1 {One item} other {# items}}"
        assert run_formatter(p, "en", {"count": 0}) == "No items"

    def test_exact_one(self):
        p = "{count, plural, =0 {No items} =1 {One item} other {# items}}"
        assert run_formatter(p, "en", {"count": 1}) == "One item"

    def test_exact_with_fallback(self):
        p = "{count, plural, =0 {No items} =1 {One item} other {# items}}"
        assert run_formatter(p, "en", {"count": 5}) == "5 items"


# ---------------------------------------------------------------------------
# English cardinal plural rules — requires evaluator
# ---------------------------------------------------------------------------

class TestPluralCardinalEnglish:
    def test_one(self):
        p = "{count, plural, one {# item} other {# items}}"
        assert run_formatter(p, "en", {"count": 1}) == "1 item"

    def test_other(self):
        p = "{count, plural, one {# item} other {# items}}"
        assert run_formatter(p, "en", {"count": 5}) == "5 items"

    def test_zero_is_other(self):
        p = "{count, plural, one {# item} other {# items}}"
        assert run_formatter(p, "en", {"count": 0}) == "0 items"


# ---------------------------------------------------------------------------
# Selectordinal — requires evaluator + parser bug 1 fix (pluralType)
# ---------------------------------------------------------------------------

class TestSelectordinal:
    def test_ordinal_first(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 1}) == "1st"

    def test_ordinal_second(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 2}) == "2nd"

    def test_ordinal_third(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 3}) == "3rd"

    def test_ordinal_fourth(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 4}) == "4th"

    def test_ordinal_eleventh(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 11}) == "11th"

    def test_ordinal_twelfth(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 12}) == "12th"

    def test_ordinal_twenty_first(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 21}) == "21st"

    def test_ordinal_twenty_second(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 22}) == "22nd"

    def test_ordinal_thirty_third(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 33}) == "33rd"

    def test_ordinal_hundredth(self):
        p = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        assert run_formatter(p, "en", {"n": 100}) == "100th"


# ---------------------------------------------------------------------------
# Plural offset — requires evaluator + parser bug 2 + formatter bug 6
# ---------------------------------------------------------------------------

class TestPluralOffset:
    def test_offset_exact_match_zero(self):
        p = "{n, plural, offset:1 =0 {nobody} =1 {just {guest}} other {{guest} and # others}}"
        assert run_formatter(p, "en", {"n": 0, "guest": "Alice"}) == "nobody"

    def test_offset_exact_match_one(self):
        p = "{n, plural, offset:1 =0 {nobody} =1 {just {guest}} other {{guest} and # others}}"
        assert run_formatter(p, "en", {"n": 1, "guest": "Alice"}) == "just Alice"

    def test_offset_hash_shows_value_minus_offset(self):
        """With offset:1, n=3 -> # should display 3-1=2."""
        p = "{n, plural, offset:1 =0 {nobody} =1 {just {guest}} other {{guest} and # others}}"
        assert run_formatter(p, "en", {"n": 3, "guest": "Alice"}) == "Alice and 2 others"

    def test_offset_hash_larger_value(self):
        """With offset:1, n=5 -> # should display 5-1=4."""
        p = "{n, plural, offset:1 =0 {nobody} =1 {just {guest}} =2 {{guest} and one more} other {{guest} and # others}}"
        assert run_formatter(p, "en", {"n": 5, "guest": "Bob"}) == "Bob and 4 others"

    def test_offset_affects_plural_rule_selection(self):
        """Plural rule uses (value - offset). offset:1, n=2 -> resolve(1) = 'one' in English."""
        p = "{n, plural, offset:1 =0 {nobody} one {{guest} plus one other} other {{guest} and # others}}"
        assert run_formatter(p, "en", {"n": 2, "guest": "Alice"}) == "Alice plus one other"


# ---------------------------------------------------------------------------
# Locale-aware # formatting — requires formatter bug 5 fix
# ---------------------------------------------------------------------------

class TestLocaleFormatting:
    def test_pound_thousands_separator(self):
        p = "{count, plural, one {# item} other {# items}}"
        assert run_formatter(p, "en-US", {"count": 1000}) == "1,000 items"

    def test_pound_millions(self):
        p = "{count, plural, one {# item} other {# items}}"
        assert run_formatter(p, "en-US", {"count": 1000000}) == "1,000,000 items"

    def test_pound_small_number_unaffected(self):
        p = "{count, plural, one {# item} other {# items}}"
        assert run_formatter(p, "en-US", {"count": 42}) == "42 items"


# ---------------------------------------------------------------------------
# Double apostrophe '' -> ' — requires parser bug 3 fix
# ---------------------------------------------------------------------------

class TestDoubleApostrophe:
    def test_basic(self):
        assert run_formatter("It''s done", "en", {}) == "It's done"

    def test_multiple(self):
        assert run_formatter("can''t won''t", "en", {}) == "can't won't"

    def test_with_argument(self):
        assert run_formatter("It''s {adj}", "en", {"adj": "great"}) == "It's great"

    def test_in_plural_body(self):
        p = "{count, plural, one {don''t} other {don''t}}"
        assert run_formatter(p, "en", {"count": 1}) == "don't"


# ---------------------------------------------------------------------------
# Escaped # via '#' in plural/selectordinal — requires parser bug 4 fix
# ---------------------------------------------------------------------------

class TestEscapedHash:
    def test_escaped_hash_in_plural_one(self):
        p = "{count, plural, one {the '#' sign} other {the '#' sign}}"
        assert run_formatter(p, "en", {"count": 1}) == "the # sign"

    def test_escaped_hash_in_plural_other(self):
        p = "{count, plural, one {the '#' sign} other {the '#' sign}}"
        assert run_formatter(p, "en", {"count": 5}) == "the # sign"

    def test_hash_at_top_level_is_literal(self):
        assert run_formatter("Price: #100", "en", {}) == "Price: #100"

    def test_apostrophe_before_non_special_is_literal(self):
        assert run_formatter("It's fine", "en", {}) == "It's fine"


# ---------------------------------------------------------------------------
# Quoted braces — requires parser bug 3+4 fix
# ---------------------------------------------------------------------------

class TestQuotedBraces:
    def test_quoted_brace_pair(self):
        result = run_formatter("This '{isn''t}' obvious", "en", {})
        assert result == "This {isn't} obvious"

    def test_quoted_individual_braces(self):
        result = run_formatter("Use '{' and '}'", "en", {})
        assert result == "Use { and }"


# ---------------------------------------------------------------------------
# Russian plural rules (one/few/many/other) — requires evaluator
# ---------------------------------------------------------------------------

class TestRussianPlural:
    def test_russian_one(self):
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 1}) == "1 item_one"

    def test_russian_few(self):
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 2}) == "2 item_few"

    def test_russian_many(self):
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 5}) == "5 item_many"

    def test_russian_21_is_one(self):
        """21 -> 'one' in Russian (i%10==1 && i%100!=11)."""
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 21}) == "21 item_one"

    def test_russian_11_is_many(self):
        """11 -> 'many' in Russian (i%100==11 is in 11..14)."""
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 11}) == "11 item_many"

    def test_russian_22_is_few(self):
        """22 -> 'few' in Russian (i%10==2, i%100==22 not in 12..14)."""
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 22}) == "22 item_few"

    def test_russian_0_is_many(self):
        """0 -> 'many' in Russian (i%10==0)."""
        p = "{n, plural, one {# item_one} few {# item_few} many {# item_many} other {# item_other}}"
        assert run_formatter(p, "ru", {"n": 0}) == "0 item_many"


# ---------------------------------------------------------------------------
# Arabic plural rules (zero/one/two/few/many/other) — requires evaluator
# ---------------------------------------------------------------------------

class TestArabicPlural:
    def test_arabic_zero(self):
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 0}) == "z"

    def test_arabic_one(self):
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 1}) == "o"

    def test_arabic_two(self):
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 2}) == "tw"

    def test_arabic_few(self):
        """7 -> few in Arabic (n%100=7, 7 in 3..10)."""
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 7}) == "f"

    def test_arabic_many(self):
        """15 -> many in Arabic (n%100=15, 15 in 11..99)."""
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 15}) == "m"

    def test_arabic_other(self):
        """100 -> other in Arabic (n%100=0, not in 3..10, not in 11..99)."""
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 100}) == "x"

    def test_arabic_103_is_few(self):
        """103 -> few in Arabic (n%100=3, 3 in 3..10)."""
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 103}) == "f"

    def test_arabic_111_is_many(self):
        """111 -> many in Arabic (n%100=11, 11 in 11..99)."""
        p = "{n, plural, zero {z} one {o} two {tw} few {f} many {m} other {x}}"
        assert run_formatter(p, "ar", {"n": 111}) == "m"


# ---------------------------------------------------------------------------
# Polish plural rules (one/few/many/other) — requires evaluator with v/i ops
# ---------------------------------------------------------------------------

class TestPolishPlural:
    def test_polish_one(self):
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 1}) == "O"

    def test_polish_few(self):
        """2 -> few in Polish (i%10=2, 2 in 2..4, i%100=2 not in 12..14)."""
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 2}) == "F"

    def test_polish_many_five(self):
        """5 -> many in Polish (i%10=5, 5 in 5..9)."""
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 5}) == "M"

    def test_polish_12_is_many(self):
        """12 -> many in Polish (i%100=12, 12 in 12..14 -- excluded from few)."""
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 12}) == "M"

    def test_polish_22_is_few(self):
        """22 -> few in Polish (i%10=2, i%100=22, 22 not in 12..14)."""
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 22}) == "F"

    def test_polish_0_is_many(self):
        """0 -> many in Polish (i!=1 and i%10=0, 0 in 0..1)."""
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 0}) == "M"

    def test_polish_112_is_many(self):
        """112 -> many in Polish (i%100=12, 12 in 12..14)."""
        p = "{n, plural, one {O} few {F} many {M} other {X}}"
        assert run_formatter(p, "pl", {"n": 112}) == "M"


# ---------------------------------------------------------------------------
# Welsh plural rules (zero/one/two/few/many/other) — requires evaluator
# ---------------------------------------------------------------------------

class TestWelshPlural:
    def test_welsh_zero(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 0}) == "Z"

    def test_welsh_one(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 1}) == "O"

    def test_welsh_two(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 2}) == "TW"

    def test_welsh_few(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 3}) == "F"

    def test_welsh_many(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 6}) == "M"

    def test_welsh_other_four(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 4}) == "X"

    def test_welsh_other_five(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 5}) == "X"

    def test_welsh_other_ten(self):
        p = "{n, plural, zero {Z} one {O} two {TW} few {F} many {M} other {X}}"
        assert run_formatter(p, "cy", {"n": 10}) == "X"


# ---------------------------------------------------------------------------
# Nested constructs
# ---------------------------------------------------------------------------

class TestNestedConstructs:
    def test_hash_in_select_inside_plural_is_literal(self):
        """# inside a select nested in plural must be literal (not substituted)."""
        p = (
            "{count, plural, "
            "one {{gender, select, male {one man} female {one woman} other {one person}}} "
            "other {{gender, select, male {# men} female {# women} other {# people}}}}"
        )
        result = run_formatter(p, "en", {"count": 5, "gender": "male"})
        assert result == "# men"

    def test_plural_inside_select(self):
        """Plural nested inside select: # should work normally."""
        p = (
            "{gender, select, "
            "male {{count, plural, one {# man} other {# men}}} "
            "female {{count, plural, one {# woman} other {# women}}} "
            "other {{count, plural, one {# person} other {# people}}}}"
        )
        assert run_formatter(p, "en", {"gender": "male", "count": 5}) == "5 men"

    def test_plural_inside_select_one(self):
        p = (
            "{gender, select, "
            "male {{count, plural, one {# man} other {# men}}} "
            "female {{count, plural, one {# woman} other {# women}}} "
            "other {{count, plural, one {# person} other {# people}}}}"
        )
        assert run_formatter(p, "en", {"gender": "female", "count": 1}) == "1 woman"


# ---------------------------------------------------------------------------
# Number format argument — should work without fixes
# ---------------------------------------------------------------------------

class TestNumberFormat:
    def test_number_default(self):
        p = "{amount, number}"
        assert run_formatter(p, "en-US", {"amount": 1234.5}) == "1,234.5"

    def test_number_integer_style(self):
        p = "{amount, number, integer}"
        assert run_formatter(p, "en-US", {"amount": 1234.56}) == "1,235"


# ---------------------------------------------------------------------------
# Locale fallback — en-US should fallback to en rules
# ---------------------------------------------------------------------------

class TestLocaleFallback:
    def test_en_us_cardinal_one(self):
        """en-US not in data, must fallback to en cardinal rules."""
        p = "{n, plural, one {singular} other {plural}}"
        assert run_formatter(p, "en-US", {"n": 1}) == "singular"

    def test_en_us_cardinal_other(self):
        p = "{n, plural, one {singular} other {plural}}"
        assert run_formatter(p, "en-US", {"n": 5}) == "plural"
