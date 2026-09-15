"""
Tests for Knuth-Bendix completion framework: LPO bug fixes, KBO
implementation, Z3 weight finder, and dual-ordering completion.

"""
import sys
sys.path.insert(0, '/app')

import pytest
from term import Var, Fun
from completion import complete
from rewriting import normalize


def mul(a, b):
    return Fun('mul', (a, b))


def inv(a):
    return Fun('inv', (a,))


e = Fun('e', ())

AXIOMS = [
    (mul(e, Var('x')), Var('x')),
    (mul(inv(Var('x')), Var('x')), e),
    (mul(mul(Var('x'), Var('y')), Var('z')),
     mul(Var('x'), mul(Var('y'), Var('z')))),
]

GROUP_SYMBOLS = {'mul': 2, 'inv': 1, 'e': 0}


# =========================================================================
# Part 1: LPO bug fixes — group theory completion with default ordering
# =========================================================================

class TestLPOCompletion:
    """Verify LPO bugs are fixed and group theory completes."""

    @pytest.fixture(scope="class")
    def rules(self):
        return complete(AXIOMS)

    def test_completion_terminates(self, rules):
        assert rules is not None
        assert len(rules) > 0

    def test_sufficient_rules(self, rules):
        assert len(rules) >= 8, (
            f"Expected >= 8 rules, got {len(rules)}: "
            + "; ".join(f"{l} -> {r}" for l, r in rules)
        )

    def test_no_excessive_rules(self, rules):
        assert len(rules) <= 20

    def test_right_identity(self, rules):
        a = Var('a')
        assert normalize(mul(a, e), rules) == a

    def test_right_inverse(self, rules):
        a = Var('a')
        assert normalize(mul(a, inv(a)), rules) == e

    def test_double_inverse(self, rules):
        a = Var('a')
        assert normalize(inv(inv(a)), rules) == a

    def test_inverse_of_identity(self, rules):
        assert normalize(inv(e), rules) == e

    def test_inverse_of_product(self, rules):
        a, b = Var('a'), Var('b')
        assert normalize(inv(mul(a, b)), rules) == mul(inv(b), inv(a))

    def test_cancel_left(self, rules):
        a, b = Var('a'), Var('b')
        assert normalize(mul(inv(a), mul(a, b)), rules) == b

    def test_cancel_right(self, rules):
        a, b = Var('a'), Var('b')
        assert normalize(mul(a, mul(inv(a), b)), rules) == b

    def test_chain_cancellation(self, rules):
        a, b, c = Var('a'), Var('b'), Var('c')
        expr = mul(inv(a), mul(a, mul(inv(b), mul(b, c))))
        assert normalize(expr, rules) == c

    def test_product_with_right_inverse(self, rules):
        a, b = Var('a'), Var('b')
        expr = mul(mul(a, b), inv(b))
        assert normalize(expr, rules) == a


# =========================================================================
# Part 2: KBO implementation correctness
# =========================================================================

class TestKBOImport:
    """Verify KBO module exports the expected API."""

    def test_imports(self):
        from kbo import KBOConfig, term_weight, var_counts, kbo_gt, kbo_ge


class TestTermWeight:
    """Verify KBO weight computation."""

    def test_variable_weight(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({'mul': 1, 'inv': 1, 'e': 1}, w0=1, precedence={})
        assert term_weight(Var('x'), cfg) == 1

    def test_variable_weight_w0_3(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({}, w0=3, precedence={})
        assert term_weight(Var('y'), cfg) == 3

    def test_constant_weight(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({'e': 2}, w0=1, precedence={})
        assert term_weight(e, cfg) == 2

    def test_unary_weight(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({'inv': 0, 'e': 1}, w0=1, precedence={})
        # inv(e) = w(inv) + w(e) = 0 + 1 = 1
        assert term_weight(inv(e), cfg) == 1

    def test_binary_weight(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({'mul': 0, 'e': 1}, w0=1, precedence={})
        # mul(e, x) = 0 + 1 + 1 = 2
        assert term_weight(mul(e, Var('x')), cfg) == 2

    def test_nested_weight(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({'mul': 0, 'inv': 0, 'e': 1}, w0=1, precedence={})
        # mul(inv(x), e) = 0 + (0 + 1) + 1 = 2
        assert term_weight(mul(inv(Var('x')), e), cfg) == 2

    def test_deep_nesting(self):
        from kbo import KBOConfig, term_weight
        cfg = KBOConfig({'mul': 0, 'inv': 0, 'e': 1}, w0=1, precedence={})
        # mul(mul(x,y), z) = 0 + (0+1+1) + 1 = 3
        x, y, z = Var('x'), Var('y'), Var('z')
        assert term_weight(mul(mul(x, y), z), cfg) == 3


class TestVarCounts:
    """Verify variable occurrence counting."""

    def test_single_var(self):
        from kbo import var_counts
        vc = var_counts(Var('x'))
        assert vc['x'] == 1

    def test_distinct_vars(self):
        from kbo import var_counts
        vc = var_counts(mul(Var('x'), Var('y')))
        assert vc['x'] == 1 and vc['y'] == 1

    def test_repeated_var(self):
        from kbo import var_counts
        vc = var_counts(mul(Var('x'), Var('x')))
        assert vc['x'] == 2

    def test_nested_repeat(self):
        from kbo import var_counts
        vc = var_counts(mul(inv(Var('x')), Var('x')))
        assert vc['x'] == 2

    def test_constant(self):
        from kbo import var_counts
        vc = var_counts(e)
        assert len(vc) == 0


class TestKBOComparisons:
    """Verify KBO comparison on specific term pairs."""

    def _cfg(self):
        from kbo import KBOConfig
        return KBOConfig(
            {'mul': 0, 'inv': 0, 'e': 1},
            w0=1,
            precedence={'inv': 2, 'mul': 1, 'e': 0}
        )

    def test_weight_gt(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        # mul(e, x) weight=2 > x weight=1, var cond holds
        assert kbo_gt(mul(e, Var('x')), Var('x'), cfg)

    def test_weight_gt_reverse(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        # x weight=1 < mul(e,x) weight=2
        assert not kbo_gt(Var('x'), mul(e, Var('x')), cfg)

    def test_var_condition_fail(self):
        from kbo import kbo_gt
        from kbo import KBOConfig
        cfg = KBOConfig({'f': 1}, w0=1, precedence={'f': 1})
        # f(x) weight=2 > y weight=1, but var condition fails: |f(x)|_y=0 < |y|_y=1
        assert not kbo_gt(Fun('f', (Var('x'),)), Var('y'), cfg)

    def test_precedence_tiebreak(self):
        from kbo import kbo_gt, KBOConfig
        cfg = KBOConfig({'f': 0, 'g': 0}, w0=1, precedence={'f': 2, 'g': 1})
        # f(x) vs g(x): same weight, same vars, f > g in precedence
        assert kbo_gt(Fun('f', (Var('x'),)), Fun('g', (Var('x'),)), cfg)

    def test_precedence_tiebreak_reverse(self):
        from kbo import kbo_gt, KBOConfig
        cfg = KBOConfig({'f': 0, 'g': 0}, w0=1, precedence={'f': 2, 'g': 1})
        assert not kbo_gt(Fun('g', (Var('x'),)), Fun('f', (Var('x'),)), cfg)

    def test_lex_tiebreak(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        x, y, z = Var('x'), Var('y'), Var('z')
        # mul(mul(x,y), z) vs mul(x, mul(y,z)): same weight=3, same vars
        # Same top mul, lex: mul(x,y) vs x -> weight 2>1 -> left wins
        assert kbo_gt(mul(mul(x, y), z), mul(x, mul(y, z)), cfg)

    def test_lex_tiebreak_reverse(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        x, y, z = Var('x'), Var('y'), Var('z')
        assert not kbo_gt(mul(x, mul(y, z)), mul(mul(x, y), z), cfg)

    def test_equal_terms(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        assert not kbo_gt(Var('x'), Var('x'), cfg)

    def test_equal_compound(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        assert not kbo_gt(mul(Var('x'), Var('y')), mul(Var('x'), Var('y')), cfg)

    def test_double_inverse_gt_var(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        # inv(inv(x)): weight=0+0+1=1, x: weight=1. Equal weight.
        # t=x is variable, s != t, var cond holds => s > t
        assert kbo_gt(inv(inv(Var('x'))), Var('x'), cfg)

    def test_inverse_of_product_orientation(self):
        from kbo import kbo_gt
        cfg = self._cfg()
        a, b = Var('a'), Var('b')
        # inv(mul(a,b)) weight=0+0+1+1=2, mul(inv(b),inv(a)) weight=0+0+1+0+1=2
        # Equal weight, top sym inv vs mul, inv > mul in prec
        assert kbo_gt(inv(mul(a, b)), mul(inv(b), inv(a)), cfg)

    def test_kbo_ge_equal(self):
        from kbo import kbo_ge
        cfg = self._cfg()
        assert kbo_ge(Var('x'), Var('x'), cfg)

    def test_kbo_ge_gt(self):
        from kbo import kbo_ge
        cfg = self._cfg()
        assert kbo_ge(mul(e, Var('x')), Var('x'), cfg)


# =========================================================================
# Part 3: Z3 weight finder
# =========================================================================

class TestWeightFinder:
    """Verify Z3-based weight finding produces valid KBO configurations."""

    def test_finds_weights(self):
        from weight_finder import find_kbo_weights
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        assert result is not None, "Z3 should find valid KBO weights for group theory"

    def test_w0_positive(self):
        from weight_finder import find_kbo_weights
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        assert result['w0'] > 0

    def test_constant_weight_bound(self):
        from weight_finder import find_kbo_weights
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        assert result['weights']['e'] >= result['w0'], \
            f"Constant e weight {result['weights']['e']} must be >= w0={result['w0']}"

    def test_weights_non_negative(self):
        from weight_finder import find_kbo_weights
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        for sym, w in result['weights'].items():
            assert w >= 0, f"Weight of {sym} is {w}, must be >= 0"

    def test_has_all_symbols(self):
        from weight_finder import find_kbo_weights
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        for sym in GROUP_SYMBOLS:
            assert sym in result['weights'], f"Missing weight for {sym}"
            assert sym in result['precedence'], f"Missing precedence for {sym}"

    def test_found_weights_orient_axioms(self):
        """Verify Z3-found weights actually orient all group theory axioms."""
        from weight_finder import find_kbo_weights
        from kbo import KBOConfig, kbo_gt
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        cfg = KBOConfig(result['weights'], result['w0'], result['precedence'])
        for lhs, rhs in AXIOMS:
            ok = kbo_gt(lhs, rhs, cfg) or kbo_gt(rhs, lhs, cfg)
            assert ok, f"Cannot orient {lhs} = {rhs} with found weights"


# =========================================================================
# Part 4: KBO-based completion of group theory
# =========================================================================

class TestKBOCompletion:
    """Verify group theory completes correctly using KBO ordering."""

    @pytest.fixture(scope="class")
    def kbo_rules(self):
        from weight_finder import find_kbo_weights
        from kbo import KBOConfig, kbo_gt
        result = find_kbo_weights(AXIOMS, GROUP_SYMBOLS)
        cfg = KBOConfig(result['weights'], result['w0'], result['precedence'])
        gt_fn = lambda s, t: kbo_gt(s, t, cfg)
        return complete(AXIOMS, gt_fn=gt_fn)

    def test_kbo_completion_succeeds(self, kbo_rules):
        assert kbo_rules is not None and len(kbo_rules) >= 8, \
            f"KBO completion produced {len(kbo_rules)} rules, expected >= 8"

    def test_kbo_no_excessive_rules(self, kbo_rules):
        assert len(kbo_rules) <= 20

    def test_kbo_right_identity(self, kbo_rules):
        a = Var('a')
        assert normalize(mul(a, e), kbo_rules) == a

    def test_kbo_right_inverse(self, kbo_rules):
        a = Var('a')
        assert normalize(mul(a, inv(a)), kbo_rules) == e

    def test_kbo_double_inverse(self, kbo_rules):
        a = Var('a')
        assert normalize(inv(inv(a)), kbo_rules) == a

    def test_kbo_inverse_of_product(self, kbo_rules):
        a, b = Var('a'), Var('b')
        assert normalize(inv(mul(a, b)), kbo_rules) == mul(inv(b), inv(a))

    def test_kbo_cancel_left(self, kbo_rules):
        a, b = Var('a'), Var('b')
        assert normalize(mul(inv(a), mul(a, b)), kbo_rules) == b

    def test_kbo_cancel_right(self, kbo_rules):
        a, b = Var('a'), Var('b')
        assert normalize(mul(a, mul(inv(a), b)), kbo_rules) == b

    def test_kbo_complex_chain(self, kbo_rules):
        a, b = Var('a'), Var('b')
        expr = mul(mul(a, b), mul(inv(b), inv(a)))
        assert normalize(expr, kbo_rules) == e

    def test_kbo_triple_inverse(self, kbo_rules):
        a = Var('a')
        assert normalize(inv(inv(inv(a))), kbo_rules) == inv(a)

    def test_kbo_nested_inverse_of_product(self, kbo_rules):
        a, b, c = Var('a'), Var('b'), Var('c')
        expr = inv(mul(a, mul(b, c)))
        expected = mul(inv(c), mul(inv(b), inv(a)))
        assert normalize(expr, kbo_rules) == expected


# =========================================================================
# Part 5: Completion accepts gt_fn parameter
# =========================================================================

class TestCompletionAPI:
    """Verify completion.complete accepts gt_fn keyword argument."""

    def test_default_ordering(self):
        """complete(axioms) should work without gt_fn (uses LPO)."""
        rules = complete(AXIOMS)
        assert len(rules) >= 8

    def test_explicit_lpo(self):
        """complete(axioms, gt_fn=lpo_gt) should work."""
        from ordering import lpo_gt
        rules = complete(AXIOMS, gt_fn=lpo_gt)
        assert len(rules) >= 8

    def test_explicit_kbo(self):
        """complete(axioms, gt_fn=kbo_gt_fn) should work."""
        from kbo import KBOConfig, kbo_gt
        cfg = KBOConfig({'mul': 0, 'inv': 0, 'e': 1}, w0=1,
                        precedence={'inv': 2, 'mul': 1, 'e': 0})
        gt_fn = lambda s, t: kbo_gt(s, t, cfg)
        rules = complete(AXIOMS, gt_fn=gt_fn)
        assert len(rules) >= 8
