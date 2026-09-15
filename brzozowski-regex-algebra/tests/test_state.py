
import sys
sys.path.insert(0, '/app')

import subprocess
import os
import re
import pytest
from regex_algebra import (
    Regex, Empty, Epsilon, Char, Alt, Seq, Star, Complement, Intersection,
    nullable, matches, is_empty, is_universal, equivalent, parse, to_dot,
    compile_to_c, generate_flex_spec,
)

AB = {'a', 'b'}


# ─── nullable ────────────────────────────────────────────────────────

class TestNullable:
    def test_empty(self):
        assert nullable(Empty()) is False

    def test_epsilon(self):
        assert nullable(Epsilon()) is True

    def test_char(self):
        assert nullable(Char('a')) is False

    def test_star_of_char(self):
        assert nullable(Star(Char('a'))) is True

    def test_star_of_empty(self):
        assert nullable(Star(Empty())) is True

    def test_alt_with_epsilon(self):
        assert nullable(Alt(Char('a'), Epsilon())) is True

    def test_alt_without_epsilon(self):
        assert nullable(Alt(Char('a'), Char('b'))) is False

    def test_seq_both_nullable(self):
        assert nullable(Seq(Star(Char('a')), Epsilon())) is True

    def test_seq_one_not_nullable(self):
        assert nullable(Seq(Char('a'), Char('b'))) is False

    def test_complement_of_char(self):
        assert nullable(Complement(Char('a'))) is True

    def test_complement_of_star(self):
        assert nullable(Complement(Star(Char('a')))) is False

    def test_intersection_both_nullable(self):
        assert nullable(Intersection(Star(Char('a')), Star(Char('b')))) is True

    def test_intersection_one_not_nullable(self):
        assert nullable(Intersection(Char('a'), Star(Char('b')))) is False


# ─── matches ─────────────────────────────────────────────────────────

class TestMatches:
    def test_char_match(self):
        assert matches(Char('a'), 'a') is True

    def test_char_no_match(self):
        assert matches(Char('a'), 'b') is False

    def test_char_too_long(self):
        assert matches(Char('a'), 'aa') is False

    def test_seq(self):
        assert matches(Seq(Char('a'), Char('b')), 'ab') is True

    def test_seq_wrong_order(self):
        assert matches(Seq(Char('a'), Char('b')), 'ba') is False

    def test_alt_first(self):
        assert matches(Alt(Char('a'), Char('b')), 'a') is True

    def test_alt_second(self):
        assert matches(Alt(Char('a'), Char('b')), 'b') is True

    def test_alt_neither(self):
        assert matches(Alt(Char('a'), Char('b')), 'c') is False

    def test_star_empty_string(self):
        assert matches(Star(Char('a')), '') is True

    def test_star_one(self):
        assert matches(Star(Char('a')), 'a') is True

    def test_star_multiple(self):
        assert matches(Star(Char('a')), 'aaa') is True

    def test_star_wrong_char(self):
        assert matches(Star(Char('a')), 'ab') is False

    def test_star_of_seq(self):
        assert matches(Star(Seq(Char('a'), Char('b'))), 'ababab') is True

    def test_star_of_seq_partial(self):
        assert matches(Star(Seq(Char('a'), Char('b'))), 'ababa') is False

    def test_complement_excludes(self):
        assert matches(Complement(Char('a')), 'a') is False

    def test_complement_includes_other_char(self):
        assert matches(Complement(Char('a')), 'b') is True

    def test_complement_includes_empty(self):
        assert matches(Complement(Char('a')), '') is True

    def test_complement_includes_longer(self):
        assert matches(Complement(Char('a')), 'aa') is True

    def test_complement_of_star(self):
        assert matches(Complement(Star(Char('a'))), 'aaa') is False
        assert matches(Complement(Star(Char('a'))), 'b') is True

    def test_intersection_accepts(self):
        r = Intersection(Star(Char('a')), Star(Alt(Char('a'), Char('b'))))
        assert matches(r, '') is True
        assert matches(r, 'aaa') is True

    def test_intersection_rejects(self):
        r = Intersection(Star(Char('a')), Star(Alt(Char('a'), Char('b'))))
        assert matches(r, 'ab') is False

    def test_nested_complement_intersection(self):
        r = Intersection(Complement(Char('a')), Complement(Char('b')))
        assert matches(r, '') is True
        assert matches(r, 'a') is False
        assert matches(r, 'b') is False
        assert matches(r, 'c') is True
        assert matches(r, 'ab') is True

    def test_ends_with_a(self):
        r = Seq(Star(Alt(Char('a'), Char('b'))), Char('a'))
        assert matches(r, 'a') is True
        assert matches(r, 'bba') is True
        assert matches(r, 'bbb') is False
        assert matches(r, '') is False


# ─── is_empty ────────────────────────────────────────────────────────

class TestIsEmpty:
    def test_empty_set(self):
        assert is_empty(Empty(), AB) is True

    def test_epsilon_not_empty(self):
        assert is_empty(Epsilon(), AB) is False

    def test_char_not_empty(self):
        assert is_empty(Char('a'), AB) is False

    def test_disjoint_intersection(self):
        assert is_empty(Intersection(Char('a'), Char('b')), AB) is True

    def test_complement_of_sigma_star(self):
        sigma_star = Star(Alt(Char('a'), Char('b')))
        assert is_empty(Complement(sigma_star), AB) is True

    def test_complement_of_empty(self):
        assert is_empty(Complement(Empty()), AB) is False

    def test_subset_via_intersection(self):
        sigma_star = Star(Alt(Char('a'), Char('b')))
        assert is_empty(Intersection(Char('a'), Complement(sigma_star)), AB) is True

    def test_seq_with_empty(self):
        assert is_empty(Seq(Empty(), Char('a')), AB) is True

    def test_complement_intersection_nonempty(self):
        r = Intersection(Complement(Char('a')), Complement(Char('b')))
        assert is_empty(r, AB) is False


# ─── is_universal ────────────────────────────────────────────────────

class TestIsUniversal:
    def test_sigma_star(self):
        sigma_star = Star(Alt(Char('a'), Char('b')))
        assert is_universal(sigma_star, AB) is True

    def test_complement_of_empty(self):
        assert is_universal(Complement(Empty()), AB) is True

    def test_char_not_universal(self):
        assert is_universal(Char('a'), AB) is False

    def test_a_star_not_universal(self):
        assert is_universal(Star(Char('a')), AB) is False

    def test_union_with_complement(self):
        r = Alt(Char('a'), Complement(Char('a')))
        assert is_universal(r, AB) is True


# ─── equivalent ──────────────────────────────────────────────────────

class TestEquivalent:
    def test_self_equivalence(self):
        r = Star(Char('a'))
        assert equivalent(r, r, AB) is True

    def test_sigma_star_two_forms(self):
        r1 = Star(Alt(Char('a'), Char('b')))
        r2 = Star(Seq(Star(Char('a')), Star(Char('b'))))
        assert equivalent(r1, r2, AB) is True

    def test_not_equivalent(self):
        assert equivalent(Char('a'), Char('b'), AB) is False

    def test_de_morgan(self):
        r1 = Complement(Alt(Char('a'), Char('b')))
        r2 = Intersection(Complement(Char('a')), Complement(Char('b')))
        assert equivalent(r1, r2, AB) is True

    def test_alt_commutative(self):
        r1 = Alt(Char('a'), Char('b'))
        r2 = Alt(Char('b'), Char('a'))
        assert equivalent(r1, r2, AB) is True

    def test_double_complement(self):
        r1 = Complement(Complement(Char('a')))
        r2 = Char('a')
        assert equivalent(r1, r2, AB) is True

    def test_intersection_with_sigma_star(self):
        sigma_star = Star(Alt(Char('a'), Char('b')))
        r = Star(Char('a'))
        assert equivalent(Intersection(r, sigma_star), r, AB) is True

    def test_distributivity(self):
        r1 = Seq(Char('a'), Alt(Char('b'), Char('c')))
        r2 = Alt(Seq(Char('a'), Char('b')), Seq(Char('a'), Char('c')))
        assert equivalent(r1, r2, {'a', 'b', 'c'}) is True


# ─── parse + matches integration ─────────────────────────────────────

class TestParse:
    def test_single_char(self):
        assert matches(parse('a'), 'a') is True
        assert matches(parse('a'), 'b') is False

    def test_concatenation(self):
        assert matches(parse('ab'), 'ab') is True
        assert matches(parse('ab'), 'a') is False

    def test_alternation(self):
        assert matches(parse('a|b'), 'a') is True
        assert matches(parse('a|b'), 'b') is True
        assert matches(parse('a|b'), 'c') is False

    def test_star(self):
        assert matches(parse('a*'), '') is True
        assert matches(parse('a*'), 'aaa') is True

    def test_grouped_star(self):
        assert matches(parse('(ab)*'), 'abab') is True
        assert matches(parse('(ab)*'), 'aba') is False

    def test_complement(self):
        assert matches(parse('~a'), 'a') is False
        assert matches(parse('~a'), 'b') is True
        assert matches(parse('~a'), '') is True

    def test_intersection(self):
        assert matches(parse('a*&(a|b)*'), 'aaa') is True
        assert matches(parse('a*&(a|b)*'), 'ab') is False

    def test_precedence_concat_over_union(self):
        r = parse('ab|cd')
        assert matches(r, 'ab') is True
        assert matches(r, 'cd') is True
        assert matches(r, 'ac') is False

    def test_precedence_star_over_concat(self):
        r = parse('a*b')
        assert matches(r, 'b') is True
        assert matches(r, 'aab') is True
        assert matches(r, 'ab') is True
        assert matches(r, 'aba') is False

    def test_precedence_complement(self):
        r = parse('~a*')
        assert matches(r, '') is False
        assert matches(r, 'a') is False
        assert matches(r, 'b') is True

    def test_epsilon_literal(self):
        assert matches(parse('@'), '') is True
        assert matches(parse('@'), 'a') is False

    def test_empty_set_literal(self):
        assert matches(parse('#'), '') is False
        assert matches(parse('#'), 'a') is False

    def test_complex_expression(self):
        r = parse('(a|b)*a')
        assert matches(r, 'a') is True
        assert matches(r, 'bba') is True
        assert matches(r, 'bbb') is False

    def test_intersection_over_union_precedence(self):
        r = parse('a&b|c')
        assert matches(r, 'c') is True
        assert matches(r, 'a') is False


# ─── DOT output ──────────────────────────────────────────────────────

class TestDotOutput:
    def test_valid_digraph_structure(self):
        dot = to_dot(Char('a'), {'a', 'b'})
        assert 'digraph' in dot
        assert '->' in dot

    def test_accepting_state_doublecircle(self):
        dot = to_dot(Epsilon(), {'a'})
        assert 'doublecircle' in dot

    def test_non_accepting_only_circle(self):
        dot = to_dot(Empty(), {'a'})
        assert 'shape=circle' in dot
        assert 'doublecircle' not in dot

    def test_graphviz_renders_simple(self):
        dot = to_dot(Char('a'), {'a'})
        result = subprocess.run(
            ['dot', '-Tsvg'], input=dot, capture_output=True, text=True
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr}"
        assert '<svg' in result.stdout

    def test_graphviz_renders_star(self):
        dot = to_dot(Star(Alt(Char('a'), Char('b'))), {'a', 'b'})
        result = subprocess.run(
            ['dot', '-Tsvg'], input=dot, capture_output=True, text=True
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr}"
        assert '<svg' in result.stdout

    def test_graphviz_renders_complement(self):
        dot = to_dot(Complement(Char('a')), {'a', 'b'})
        result = subprocess.run(
            ['dot', '-Tsvg'], input=dot, capture_output=True, text=True
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr}"
        assert '<svg' in result.stdout
        # ~a is nullable so the start state should be accepting
        assert 'doublecircle' in dot

    def test_graphviz_renders_intersection(self):
        dot = to_dot(Intersection(Star(Char('a')), Star(Alt(Char('a'), Char('b')))), AB)
        result = subprocess.run(
            ['dot', '-Tsvg'], input=dot, capture_output=True, text=True
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr}"
        assert '<svg' in result.stdout

    def test_start_marker_present(self):
        dot = to_dot(Char('a'), {'a'})
        # There should be an invisible start node with an edge to the start state
        assert 'shape=none' in dot or 'shape="none"' in dot

    def test_transitions_labeled(self):
        dot = to_dot(Char('a'), {'a', 'b'})
        # Should have transitions labeled with 'a' and 'b'
        assert 'label="a"' in dot or "label='a'" in dot
        assert 'label="b"' in dot or "label='b'" in dot


# ─── compile (C code generation + gcc) ───────────────────────────────

class TestCompile:
    """Test DFA-to-C compilation and gcc integration."""

    def _compile_and_run(self, expr_str, alphabet_str, inputs):
        """Parse expr, generate C, compile with gcc, run on inputs."""
        r = parse(expr_str)
        c_source = compile_to_c(r, set(alphabet_str))

        c_path = f'/tmp/_test_compile_{os.getpid()}.c'
        bin_path = f'/tmp/_test_compile_{os.getpid()}'
        try:
            with open(c_path, 'w') as f:
                f.write(c_source)

            gcc = subprocess.run(
                ['gcc', '-o', bin_path, c_path, '-Wall'],
                capture_output=True, text=True,
            )
            assert gcc.returncode == 0, f"gcc failed:\n{gcc.stderr}"

            input_text = '\n'.join(inputs) + '\n'
            run = subprocess.run(
                [bin_path], input=input_text, capture_output=True, text=True,
            )
            assert run.returncode == 0, f"binary failed:\n{run.stderr}"
            return run.stdout.strip().split('\n')
        finally:
            for p in (c_path, bin_path):
                if os.path.exists(p):
                    os.unlink(p)

    def test_compile_single_char(self):
        results = self._compile_and_run('a', 'ab', ['a', 'b', ''])
        assert results == ['accept', 'reject', 'reject']

    def test_compile_star(self):
        results = self._compile_and_run('a*', 'ab', ['', 'a', 'aaa', 'b', 'ab'])
        assert results == ['accept', 'accept', 'accept', 'reject', 'reject']

    def test_compile_concat(self):
        results = self._compile_and_run('a*b', 'ab', ['b', 'ab', 'aab', 'ba', 'a'])
        assert results == ['accept', 'accept', 'accept', 'reject', 'reject']

    def test_compile_complement(self):
        results = self._compile_and_run('~a', 'ab', ['a', 'b', '', 'aa', 'ab'])
        assert results == ['reject', 'accept', 'accept', 'accept', 'accept']

    def test_compile_intersection(self):
        results = self._compile_and_run('a*&(a|b)*', 'ab', ['', 'aaa', 'ab', 'b'])
        assert results == ['accept', 'accept', 'reject', 'reject']

    def test_compile_complex(self):
        # (a|b)*a — strings over {a,b} ending with a
        results = self._compile_and_run('(a|b)*a', 'ab', ['a', 'ba', 'bba', 'b', 'bb', ''])
        assert results == ['accept', 'accept', 'accept', 'reject', 'reject', 'reject']

    def test_compile_de_morgan(self):
        # ~(a|b) should be same as ~a&~b — test with the intersection form
        results = self._compile_and_run('~a&~b', 'ab', ['', 'a', 'b', 'ab', 'aa'])
        assert results == ['accept', 'reject', 'reject', 'accept', 'accept']

    def test_compile_nonalphabet_chars_rejected(self):
        # Characters outside the alphabet should cause rejection
        results = self._compile_and_run('a*', 'a', ['a', 'aaa', 'b', 'ab'])
        assert results == ['accept', 'accept', 'reject', 'reject']

    def test_cli_compile(self):
        """Test compile via the rex CLI."""
        bin_path = f'/tmp/_test_cli_compile_{os.getpid()}'
        try:
            r = subprocess.run(
                ['/app/rex', 'compile', '(a|b)*', 'ab', bin_path],
                capture_output=True, text=True,
            )
            assert r.returncode == 0, f"rex compile failed: {r.stderr}"
            assert os.path.isfile(bin_path), "Binary not created"

            run = subprocess.run(
                [bin_path], input='a\nab\nbba\n\n',
                capture_output=True, text=True,
            )
            assert run.returncode == 0
            results = run.stdout.strip().split('\n')
            assert results == ['accept', 'accept', 'accept', 'accept']
        finally:
            if os.path.exists(bin_path):
                os.unlink(bin_path)


# ─── flex-spec (flex .l generation + flex + gcc) ─────────────────────

class TestFlexSpec:
    """Test DFA-to-flex-spec generation, flex compilation, and gcc integration."""

    def _build_and_run(self, expr_str, alphabet_str, input_str):
        """Parse expr, generate .l, compile with flex+gcc, run on input_str."""
        r = parse(expr_str)
        spec = generate_flex_spec(r, set(alphabet_str))

        pid = os.getpid()
        l_path = f'/tmp/_test_flex_{pid}.l'
        c_path = f'/tmp/_test_flex_{pid}.yy.c'
        bin_path = f'/tmp/_test_flex_{pid}'
        try:
            with open(l_path, 'w') as f:
                f.write(spec)

            flex_r = subprocess.run(
                ['flex', '-o', c_path, l_path],
                capture_output=True, text=True,
            )
            assert flex_r.returncode == 0, f"flex failed:\n{flex_r.stderr}"

            gcc_r = subprocess.run(
                ['gcc', '-o', bin_path, c_path],
                capture_output=True, text=True,
            )
            assert gcc_r.returncode == 0, f"gcc failed:\n{gcc_r.stderr}"

            # Use printf-style input (no trailing newline) so newline
            # doesn't get processed as a non-alphabet character.
            run = subprocess.run(
                [bin_path], input=input_str,
                capture_output=True, text=True,
            )
            return run.stdout.strip()
        finally:
            for p in (l_path, c_path, bin_path):
                if os.path.exists(p):
                    os.unlink(p)

    def test_flex_spec_compiles(self):
        """The generated .l file compiles successfully via flex+gcc."""
        r = parse('a*')
        spec = generate_flex_spec(r, AB)
        pid = os.getpid()
        l_path = f'/tmp/_test_flex_comp_{pid}.l'
        c_path = f'/tmp/_test_flex_comp_{pid}.yy.c'
        bin_path = f'/tmp/_test_flex_comp_{pid}'
        try:
            with open(l_path, 'w') as f:
                f.write(spec)
            flex_r = subprocess.run(['flex', '-o', c_path, l_path], capture_output=True, text=True)
            assert flex_r.returncode == 0, f"flex failed:\n{flex_r.stderr}"
            gcc_r = subprocess.run(['gcc', '-o', bin_path, c_path], capture_output=True, text=True)
            assert gcc_r.returncode == 0, f"gcc failed:\n{gcc_r.stderr}"
            assert os.path.isfile(bin_path)
        finally:
            for p in (l_path, c_path, bin_path):
                if os.path.exists(p):
                    os.unlink(p)

    def test_flex_char_accept(self):
        assert self._build_and_run('a', 'ab', 'a') == 'accept'

    def test_flex_char_reject(self):
        assert self._build_and_run('a', 'ab', 'b') == 'reject'

    def test_flex_star_empty(self):
        assert self._build_and_run('a*', 'ab', '') == 'accept'

    def test_flex_star_repeat(self):
        assert self._build_and_run('a*', 'ab', 'aaa') == 'accept'

    def test_flex_star_reject(self):
        assert self._build_and_run('a*', 'ab', 'b') == 'reject'

    def test_flex_complement_accept(self):
        assert self._build_and_run('~a', 'ab', 'b') == 'accept'

    def test_flex_complement_reject(self):
        assert self._build_and_run('~a', 'ab', 'a') == 'reject'

    def test_flex_complement_empty(self):
        assert self._build_and_run('~a', 'ab', '') == 'accept'

    def test_flex_intersection(self):
        assert self._build_and_run('a*&(a|b)*', 'ab', 'aaa') == 'accept'
        assert self._build_and_run('a*&(a|b)*', 'ab', 'ab') == 'reject'

    def test_flex_sigma_star(self):
        assert self._build_and_run('(a|b)*', 'ab', 'abba') == 'accept'
        assert self._build_and_run('(a|b)*', 'ab', '') == 'accept'

    def test_flex_uses_exclusive_states(self):
        """The generated .l file must use %x for DFA state encoding."""
        r = parse('a*b')
        spec = generate_flex_spec(r, AB)
        assert '%x' in spec, "flex spec must use exclusive start conditions (%x)"

    def test_flex_has_noyywrap(self):
        """The generated .l file must use %option noyywrap."""
        r = parse('a')
        spec = generate_flex_spec(r, AB)
        assert 'noyywrap' in spec, "flex spec must use %option noyywrap"

    def test_cli_flex_spec(self):
        """Test flex-spec via the rex CLI."""
        pid = os.getpid()
        l_path = f'/tmp/_test_cli_flex_{pid}.l'
        c_path = f'/tmp/_test_cli_flex_{pid}.yy.c'
        bin_path = f'/tmp/_test_cli_flex_{pid}'
        try:
            r = subprocess.run(
                ['/app/rex', 'flex-spec', '(a|b)*a', 'ab', l_path],
                capture_output=True, text=True,
            )
            assert r.returncode == 0, f"rex flex-spec failed: {r.stderr}"
            assert os.path.isfile(l_path), ".l file not created"

            flex_r = subprocess.run(['flex', '-o', c_path, l_path], capture_output=True, text=True)
            assert flex_r.returncode == 0, f"flex failed:\n{flex_r.stderr}"
            gcc_r = subprocess.run(['gcc', '-o', bin_path, c_path], capture_output=True, text=True)
            assert gcc_r.returncode == 0, f"gcc failed:\n{gcc_r.stderr}"

            run = subprocess.run([bin_path], input='bba', capture_output=True, text=True)
            assert 'accept' in run.stdout

            run = subprocess.run([bin_path], input='bb', capture_output=True, text=True)
            assert 'reject' in run.stdout
        finally:
            for p in (l_path, c_path, bin_path):
                if os.path.exists(p):
                    os.unlink(p)


# ─── CLI integration ─────────────────────────────────────────────────

class TestCLI:
    def test_match_true(self):
        r = subprocess.run(
            ['/app/rex', 'match', 'a', 'a'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_match_false(self):
        r = subprocess.run(
            ['/app/rex', 'match', 'a', 'b'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'false'

    def test_match_star(self):
        r = subprocess.run(
            ['/app/rex', 'match', 'a*', 'aaa'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_match_empty_string(self):
        r = subprocess.run(
            ['/app/rex', 'match', 'a*', ''],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_match_complement(self):
        r = subprocess.run(
            ['/app/rex', 'match', '~a', 'b'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_empty_true(self):
        r = subprocess.run(
            ['/app/rex', 'empty', 'a&b', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_empty_false(self):
        r = subprocess.run(
            ['/app/rex', 'empty', 'a', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'false'

    def test_universal_true(self):
        r = subprocess.run(
            ['/app/rex', 'universal', '(a|b)*', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_universal_false(self):
        r = subprocess.run(
            ['/app/rex', 'universal', 'a*', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'false'

    def test_equivalent_true(self):
        r = subprocess.run(
            ['/app/rex', 'equivalent', '(a|b)*', '(a*b*)*', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_equivalent_false(self):
        r = subprocess.run(
            ['/app/rex', 'equivalent', 'a', 'b', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'false'

    def test_equivalent_de_morgan(self):
        r = subprocess.run(
            ['/app/rex', 'equivalent', '~(a|b)', '~a&~b', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == 'true'

    def test_dot_produces_valid_svg(self):
        r = subprocess.run(
            ['/app/rex', 'dot', 'a*', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert 'digraph' in r.stdout
        dot_result = subprocess.run(
            ['dot', '-Tsvg'], input=r.stdout,
            capture_output=True, text=True
        )
        assert dot_result.returncode == 0
        assert '<svg' in dot_result.stdout

    def test_dot_complement_expression(self):
        r = subprocess.run(
            ['/app/rex', 'dot', '~(a|b)', 'ab'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        dot_result = subprocess.run(
            ['dot', '-Tsvg'], input=r.stdout,
            capture_output=True, text=True
        )
        assert dot_result.returncode == 0
