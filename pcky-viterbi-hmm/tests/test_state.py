
"""
Tests for probabilistic NLP analysis toolkit.
Verifies parsing, probability computation, tree extraction,
evaluation metrics, Graphviz output, and sequence decoding.
"""
import sys
import math
import os
import subprocess
import pytest

sys.path.insert(0, '/app')


# ============================================================
# Grammar 1 Tests: Standard PCFG
# ============================================================

class TestGrammar1Acceptance:
    """Test sentence acceptance/rejection with grammar1."""

    @pytest.fixture(autouse=True)
    def load_grammar(self):
        from pcky import Grammar
        self.grammar = Grammar.from_file('/app/data/grammar1.cfg')

    def test_accept_simple_sentence(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the flight includes a meal")
        assert result['accepted'] is True

    def test_accept_ambiguous_sentence(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "book the flight through Houston")
        assert result['accepted'] is True

    def test_accept_aux_sentence(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "does Houston prefer the flight")
        assert result['accepted'] is True

    def test_accept_pronoun_subject(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "I prefer a meal")
        assert result['accepted'] is True

    def test_reject_no_verb(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the the the")
        assert result['accepted'] is False

    def test_reject_single_noun(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "Houston")
        assert result['accepted'] is False


class TestGrammar1BestProbability:
    """Test most-probable-parse probabilities with grammar1."""

    @pytest.fixture(autouse=True)
    def load_grammar(self):
        from pcky import Grammar
        self.grammar = Grammar.from_file('/app/data/grammar1.cfg')

    def test_simple_sentence_best(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the flight includes a meal")
        assert abs(result['best_prob'] - 2.916e-06) < 1e-12

    def test_ambiguous_sentence_best(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "book the flight through Houston")
        assert abs(result['best_prob'] - 3.645e-07) < 1e-13

    def test_aux_sentence_best(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "does Houston prefer the flight")
        assert abs(result['best_prob'] - 3.4992e-05) < 1e-11

    def test_pronoun_sentence_best(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "I prefer a meal")
        assert abs(result['best_prob'] - 2.016e-05) < 1e-11


class TestGrammar1TotalProbability:
    """Test total probability (sum over all derivations) with grammar1."""

    @pytest.fixture(autouse=True)
    def load_grammar(self):
        from pcky import Grammar
        self.grammar = Grammar.from_file('/app/data/grammar1.cfg')

    def test_unambiguous_total_equals_best(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the flight includes a meal")
        # Only one derivation, so total == best
        assert abs(result['total_prob'] - result['best_prob']) < 1e-12

    def test_ambiguous_total_greater_than_best(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "book the flight through Houston")
        # Multiple derivations (PP attachment ambiguity), so total > best
        assert result['total_prob'] > result['best_prob']
        assert abs(result['total_prob'] - 5.103e-07) < 1e-13


class TestGrammar1ParseTree:
    """Test parse tree extraction with grammar1."""

    @pytest.fixture(autouse=True)
    def load_grammar(self):
        from pcky import Grammar
        self.grammar = Grammar.from_file('/app/data/grammar1.cfg')

    def test_simple_parse_tree(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the flight includes a meal")
        expected = "[S [NP [Det the] [Nominal [Noun flight]]] [VP [Verb includes] [NP [Det a] [Nominal [Noun meal]]]]]"
        assert result['best_parse'] == expected

    def test_no_internal_artifacts(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "book the flight through Houston")
        tree = result['best_parse']
        # Must not contain any artificial symbols from preprocessing
        assert '@' not in tree

    def test_ambiguous_tree_structure(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "book the flight through Houston")
        tree = result['best_parse']
        assert "[VP [Verb book]" in tree
        assert "[PP [Preposition through]" in tree

    def test_aux_parse_tree(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "does Houston prefer the flight")
        expected = "[S [Aux does] [NP [Proper-Noun Houston]] [VP [Verb prefer] [NP [Det the] [Nominal [Noun flight]]]]]"
        assert result['best_parse'] == expected

    def test_rejected_returns_none(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the the the")
        assert result['best_parse'] is None


# ============================================================
# Grammar 2 Tests: Complex grammar with multi-symbol rules
# ============================================================

class TestGrammar2:
    """Test parser with grammar2 (3+ RHS symbol rules)."""

    @pytest.fixture(autouse=True)
    def load_grammar(self):
        from pcky import Grammar
        self.grammar = Grammar.from_file('/app/data/grammar2.cfg')

    def test_accept_adj_noun(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "the big dog chased a cat")
        assert result['accepted'] is True
        assert abs(result['best_prob'] - 3.54375e-06) < 1e-12

    def test_ambiguous_pp_attachment(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "Rex saw the cat in the park")
        assert result['accepted'] is True
        # Multiple derivations due to PP attachment ambiguity
        assert result['total_prob'] > result['best_prob']
        assert abs(result['best_prob'] - 1.1025e-06) < 1e-12
        assert abs(result['total_prob'] - 2.205e-06) < 1e-12

    def test_reject_bad_sentence(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "quickly the cat")
        assert result['accepted'] is False

    def test_ternary_rule_output(self):
        """Test that rules with 3 RHS symbols produce clean output."""
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "he chased the dog quickly")
        assert result['accepted'] is True
        tree = result['best_parse']
        # No internal artifacts
        assert '@' not in tree
        # Three-child VP structure must be present
        assert "[VP [Verb chased]" in tree
        assert "[Adv quickly]" in tree
        assert abs(result['best_prob'] - 1.26e-05) < 1e-11

    def test_reject_adv_without_valid_structure(self):
        from pcky import parse_sentence
        result = parse_sentence(self.grammar, "slowly he ate the fish")
        assert result['accepted'] is False


# ============================================================
# Labeled Precision/Recall Tests
# ============================================================

class TestLabeledPrecisionRecall:
    """Test labeled precision and recall computation."""

    def test_exact_match(self):
        from pcky import labeled_precision_recall
        tree = "[S [NP [Pronoun I]] [VP [Verb book] [NP [Det a] [Nominal [Noun flight]]] [PP [Preposition to] [NP [Proper-Noun Houston]]]]]"
        p, r = labeled_precision_recall(tree, tree)
        assert abs(p - 1.0) < 1e-10
        assert abs(r - 1.0) < 1e-10

    def test_pp_attachment_difference(self):
        from pcky import labeled_precision_recall
        # High PP attachment (PP sister of NP under VP)
        pred = "[S [NP [Pronoun I]] [VP [Verb book] [NP [Det a] [Nominal [Noun flight]]] [PP [Preposition to] [NP [Proper-Noun Houston]]]]]"
        # Low PP attachment (PP inside Nominal under NP)
        gold = "[S [NP [Pronoun I]] [VP [Verb book] [NP [Det a] [Nominal [Noun flight] [PP [Preposition to] [NP [Proper-Noun Houston]]]]]]]"
        p, r = labeled_precision_recall(pred, gold)
        # 5 of 7 non-preterminal constituent spans match
        assert abs(p - 5.0 / 7.0) < 1e-10
        assert abs(r - 5.0 / 7.0) < 1e-10

    def test_sexpr_roundtrip(self):
        from pcky import parse_sexpr, tree_to_sexpr
        original = "[S [NP [Det the] [Nominal [Noun flight]]] [VP [Verb includes] [NP [Det a] [Nominal [Noun meal]]]]]"
        tree = parse_sexpr(original)
        reconstructed = tree_to_sexpr(tree)
        assert reconstructed == original


# ============================================================
# Graphviz DOT / SVG Tests
# ============================================================

class TestGraphviz:
    """Test DOT format generation and SVG rendering."""

    @pytest.fixture(autouse=True)
    def load_grammar(self):
        from pcky import Grammar
        self.grammar = Grammar.from_file('/app/data/grammar1.cfg')

    def test_dot_output_format(self):
        from pcky import parse_sentence, tree_to_dot
        result = parse_sentence(self.grammar, "the flight includes a meal")
        dot = tree_to_dot(result['best_parse'])
        assert 'digraph' in dot
        assert '->' in dot
        assert dot.strip().endswith('}')

    def test_dot_contains_tree_labels(self):
        from pcky import parse_sentence, tree_to_dot
        result = parse_sentence(self.grammar, "the flight includes a meal")
        dot = tree_to_dot(result['best_parse'])
        for label in ['S', 'NP', 'VP', 'Det', 'Noun', 'Verb', 'Nominal']:
            assert label in dot, f"Missing label {label} in DOT output"
        for word in ['the', 'flight', 'includes', 'a', 'meal']:
            assert word in dot, f"Missing word {word} in DOT output"

    def test_dot_renders_to_svg(self):
        """Verify DOT output can be rendered by graphviz dot command."""
        from pcky import parse_sentence, tree_to_dot
        result = parse_sentence(self.grammar, "the flight includes a meal")
        dot = tree_to_dot(result['best_parse'])
        with open('/tmp/test_parse.dot', 'w') as f:
            f.write(dot)
        proc = subprocess.run(
            ['dot', '-Tsvg', '/tmp/test_parse.dot', '-o', '/tmp/test_parse.svg'],
            capture_output=True, text=True
        )
        assert proc.returncode == 0, f"graphviz dot failed: {proc.stderr}"
        with open('/tmp/test_parse.svg') as f:
            svg = f.read()
        assert '<svg' in svg
        assert 'NP' in svg

    def test_render_script_produces_svg(self):
        """Test the render_trees.sh end-to-end pipeline."""
        proc = subprocess.run(
            ['bash', '/app/render_trees.sh', '/app/data/grammar1.cfg', 'I prefer a meal'],
            capture_output=True, text=True, cwd='/app'
        )
        assert proc.returncode == 0, f"render_trees.sh failed: {proc.stderr}\n{proc.stdout}"
        assert os.path.exists('/app/output/tree.svg'), "SVG file not created"
        with open('/app/output/tree.svg') as f:
            svg = f.read()
        assert '<svg' in svg


# ============================================================
# HMM Decoder Tests
# ============================================================

class TestHMMDecoder:
    """Test HMM sequence decoder in probability and log space."""

    @pytest.fixture(autouse=True)
    def load_hmm(self):
        from hmm import HMM
        self.hmm = HMM.from_file('/app/data/hmm_model.txt')

    def test_hmm_states(self):
        assert 'HOT' in self.hmm.states
        assert 'COLD' in self.hmm.states

    def test_decode_long_sequence(self):
        from hmm import decode
        obs = ['3', '3', '1', '1', '2', '2', '3', '1', '3']
        path, prob = decode(self.hmm, obs)
        assert path == ['HOT', 'HOT', 'COLD', 'COLD', 'HOT', 'HOT', 'HOT', 'HOT', 'HOT']
        assert abs(prob - 1.982634393600000e-06) < 1e-15

    def test_decode_short_sequence(self):
        from hmm import decode
        obs = ['3', '1', '3']
        path, prob = decode(self.hmm, obs)
        assert path == ['HOT', 'HOT', 'HOT']
        assert abs(prob - 1.2544e-02) < 1e-08

    def test_decode_single_obs(self):
        from hmm import decode
        obs = ['1']
        path, prob = decode(self.hmm, obs)
        # HOT: 0.8*0.2=0.16, COLD: 0.2*0.5=0.10 -> HOT wins
        assert path == ['HOT']
        assert abs(prob - 0.16) < 1e-10

    def test_decode_log_matches_prob(self):
        from hmm import decode, decode_log
        obs = ['3', '3', '1', '1', '2', '2', '3', '1', '3']
        path_p, prob = decode(self.hmm, obs)
        path_l, log_prob = decode_log(self.hmm, obs)
        assert path_p == path_l
        assert abs(math.exp(log_prob) - prob) < 1e-15

    def test_decode_log_value(self):
        from hmm import decode_log
        obs = ['3', '3', '1', '1', '2', '2', '3', '1', '3']
        _, log_prob = decode_log(self.hmm, obs)
        assert abs(log_prob - (-13.131084095772872)) < 1e-8

    def test_decode_reference_sequence(self):
        """Verify decode on a reference HMM problem."""
        from hmm import decode
        obs = ['3', '1', '1']
        path, prob = decode(self.hmm, obs)
        assert path == ['HOT', 'COLD', 'COLD']
        assert abs(prob - 0.0144) < 1e-10


# ============================================================
# Integration Tests
# ============================================================

class TestIntegration:
    """End-to-end tests combining parsing and evaluation."""

    def test_parse_then_evaluate_perfect(self):
        from pcky import Grammar, parse_sentence, labeled_precision_recall
        grammar = Grammar.from_file('/app/data/grammar1.cfg')
        result = parse_sentence(grammar, "the flight includes a meal")
        gold = "[S [NP [Det the] [Nominal [Noun flight]]] [VP [Verb includes] [NP [Det a] [Nominal [Noun meal]]]]]"
        p, r = labeled_precision_recall(result['best_parse'], gold)
        assert abs(p - 1.0) < 1e-10
        assert abs(r - 1.0) < 1e-10

    def test_grammar2_parse_then_evaluate(self):
        from pcky import Grammar, parse_sentence, labeled_precision_recall
        grammar = Grammar.from_file('/app/data/grammar2.cfg')
        result = parse_sentence(grammar, "the big dog chased a cat")
        gold = "[S [NP [Det the] [Nominal [Adj big] [Noun dog]]] [VP [Verb chased] [NP [Det a] [Nominal [Noun cat]]]]]"
        p, r = labeled_precision_recall(result['best_parse'], gold)
        assert abs(p - 1.0) < 1e-10
        assert abs(r - 1.0) < 1e-10

    def test_cross_grammar_sentences(self):
        from pcky import Grammar, parse_sentence
        g1 = Grammar.from_file('/app/data/grammar1.cfg')
        g2 = Grammar.from_file('/app/data/grammar2.cfg')
        r1 = parse_sentence(g1, "I prefer a meal")
        assert r1['accepted'] is True
        r2 = parse_sentence(g2, "the big dog chased a cat")
        assert r2['accepted'] is True
