"""

Tests for PCFG Grammar Induction Pipeline.
Verifies EM correctness, SQLite database, Viterbi parses, and SVG generation.
"""

import json
import subprocess
import pytest
import math
import os
import re
import sqlite3
from collections import defaultdict


def run_pipeline(iterations):
    result = subprocess.run(
        ['/app/pcfg_pipeline.sh',
         '--grammar', '/app/grammar.gr',
         '--corpus', '/app/corpus.txt',
         '--iterations', str(iterations)],
        capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, (
        "Pipeline exited with code {}.\nstderr: {}".format(
            result.returncode, result.stderr[:1000])
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail("Output is not valid JSON: {}\nstdout: {}".format(
            e, result.stdout[:500]))


@pytest.fixture(scope="module")
def all_outputs():
    """Run pipeline with 0 iterations, then 20 iterations.
    The 20-iteration run is last so its DB/SVGs are what tests inspect."""
    out0 = run_pipeline(0)
    out20 = run_pipeline(20)
    return out0, out20


@pytest.fixture(scope="module")
def output_0(all_outputs):
    return all_outputs[0]


@pytest.fixture(scope="module")
def output_20(all_outputs):
    return all_outputs[1]


def extract_leaves(tree_str):
    """Extract leaf words from a parenthesized parse tree."""
    leaves = []
    i = 0
    while i < len(tree_str):
        if tree_str[i] == '(':
            i += 1
            while i < len(tree_str) and tree_str[i] != ' ' and tree_str[i] != ')':
                i += 1
        elif tree_str[i] in ') ':
            i += 1
        else:
            end = i
            while end < len(tree_str) and tree_str[end] not in ' )':
                end += 1
            leaves.append(tree_str[i:end])
            i = end
    return leaves


# ==================================================================
# JSON Output Format Tests
# ==================================================================

class TestOutputFormat:
    def test_has_required_keys(self, output_20):
        for key in ["initial_ll", "iteration_lls", "final_rules",
                     "sentence_lls"]:
            assert key in output_20, "Missing key: {}".format(key)

    def test_iteration_lls_length(self, output_20):
        assert len(output_20["iteration_lls"]) == 20

    def test_sentence_lls_length(self, output_20):
        assert len(output_20["sentence_lls"]) == 8

    def test_rule_count(self, output_20):
        assert len(output_20["final_rules"]) == 18

    def test_zero_iterations_empty_lls(self, output_0):
        assert len(output_0["iteration_lls"]) == 0


# ==================================================================
# Inside Algorithm Tests
# ==================================================================

class TestInsideAlgorithm:
    def test_initial_ll_value(self, output_20):
        expected = -74.2528
        assert abs(output_20["initial_ll"] - expected) < 0.05, (
            "Initial LL = {:.4f}, expected ~ {}".format(
                output_20["initial_ll"], expected))

    def test_initial_ll_consistency(self, output_0):
        total = sum(output_0["sentence_lls"])
        assert abs(total - output_0["initial_ll"]) < 1e-4

    def test_first_sentence_initial_ll(self, output_0):
        expected = -6.6077
        assert abs(output_0["sentence_lls"][0] - expected) < 0.02

    def test_second_sentence_initial_ll(self, output_0):
        expected = -7.0131
        assert abs(output_0["sentence_lls"][1] - expected) < 0.02

    def test_pp_sentence_initial_ll(self, output_0):
        expected = -10.4019
        assert abs(output_0["sentence_lls"][2] - expected) < 0.02

    def test_v_pp_sentence_initial_ll(self, output_0):
        expected = -7.4062
        assert abs(output_0["sentence_lls"][6] - expected) < 0.02

    def test_sentence_lls_negative(self, output_20):
        for i, ll in enumerate(output_20["sentence_lls"]):
            assert ll < 0, "Sentence {} LL={} should be negative".format(i, ll)


# ==================================================================
# EM Convergence Tests
# ==================================================================

class TestEMConvergence:
    def test_monotonicity(self, output_20):
        lls = [output_20["initial_ll"]] + output_20["iteration_lls"]
        for i in range(1, len(lls)):
            assert lls[i] >= lls[i - 1] - 1e-4, (
                "LL decreased at iteration {}: {:.6f} -> {:.6f}".format(
                    i, lls[i - 1], lls[i]))

    def test_significant_improvement(self, output_20):
        improvement = output_20["iteration_lls"][-1] - output_20["initial_ll"]
        assert improvement > 5.0

    def test_convergence(self, output_20):
        lls = output_20["iteration_lls"]
        delta = abs(lls[-1] - lls[-2])
        assert delta < 0.1

    def test_final_ll_value(self, output_20):
        final_ll = output_20["iteration_lls"][-1]
        assert -70.0 < final_ll < -55.0


# ==================================================================
# M-Step Tests
# ==================================================================

class TestMStep:
    def test_normalization(self, output_20):
        lhs_sums = defaultdict(float)
        for rule in output_20["final_rules"]:
            prob, lhs, rhs = rule
            lhs_sums[lhs] += prob
        for lhs, total in lhs_sums.items():
            assert abs(total - 1.0) < 0.005, (
                "Rules for '{}' sum to {:.6f}".format(lhs, total))

    def test_nonneg_probabilities(self, output_20):
        for rule in output_20["final_rules"]:
            assert rule[0] >= -1e-10

    def test_unused_rule_converges_to_zero(self, output_20):
        for rule in output_20["final_rules"]:
            if rule[1] == "NP" and rule[2] == ["N", "N"]:
                assert rule[0] < 0.01
                return
        pytest.fail("Rule NP -> N N not found")

    def test_rule_structure_preserved(self, output_20):
        expected_rules = [
            ("S", ["NP", "VP"]),
            ("VP", ["V", "NP"]),
            ("VP", ["VP", "PP"]),
            ("VP", ["V", "PP"]),
            ("NP", ["Det", "N"]),
            ("NP", ["NP", "PP"]),
            ("NP", ["N", "N"]),
            ("PP", ["P", "NP"]),
            ("Det", ["the"]),
            ("Det", ["a"]),
            ("N", ["dog"]),
            ("N", ["cat"]),
            ("N", ["park"]),
            ("N", ["fish"]),
            ("V", ["saw"]),
            ("V", ["ate"]),
            ("P", ["in"]),
            ("P", ["with"]),
        ]
        actual_rules = [(r[1], r[2]) for r in output_20["final_rules"]]
        assert actual_rules == expected_rules


# ==================================================================
# Consistency Tests
# ==================================================================

class TestConsistency:
    def test_sentence_lls_sum_to_total(self, output_20):
        total = sum(output_20["sentence_lls"])
        expected = output_20["iteration_lls"][-1]
        assert abs(total - expected) < 0.01

    def test_initial_ll_matches_between_runs(self, output_20, output_0):
        assert abs(output_20["initial_ll"] - output_0["initial_ll"]) < 1e-6


# ==================================================================
# SQLite Database Schema Tests
# ==================================================================

class TestSQLiteSchema:
    def test_database_exists(self, output_20):
        assert os.path.exists('/app/grammar.db'), "grammar.db not found"

    def test_tables_exist(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in c.fetchall()}
        conn.close()
        required = {'rules', 'iterations', 'rule_history', 'sentence_parses'}
        missing = required - tables
        assert not missing, "Missing tables: {}".format(missing)

    def test_rules_columns(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(rules)")
        cols = {row[1]: row[2] for row in c.fetchall()}
        conn.close()
        assert 'rule_id' in cols
        assert 'lhs' in cols
        assert 'rhs' in cols
        assert 'initial_prob' in cols
        assert 'final_prob' in cols

    def test_iterations_columns(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(iterations)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert cols >= {'iteration', 'corpus_ll'}

    def test_rule_history_columns(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(rule_history)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert cols >= {'rule_id', 'iteration', 'probability'}

    def test_sentence_parses_columns(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(sentence_parses)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert cols >= {'sentence_id', 'sentence', 'log_likelihood',
                        'viterbi_tree'}


# ==================================================================
# SQLite Data Integrity Tests
# ==================================================================

class TestSQLiteData:
    def test_rules_count(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM rules")
        count = c.fetchone()[0]
        conn.close()
        assert count == 18

    def test_iterations_count(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM iterations")
        count = c.fetchone()[0]
        conn.close()
        assert count == 20

    def test_rule_history_count(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM rule_history")
        count = c.fetchone()[0]
        conn.close()
        assert count == 18 * 20

    def test_sentence_parses_count(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sentence_parses")
        count = c.fetchone()[0]
        conn.close()
        assert count == 8

    def test_rule_probs_sum_to_one_in_db(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT lhs, SUM(final_prob) FROM rules GROUP BY lhs")
        for lhs, total in c.fetchall():
            assert abs(total - 1.0) < 0.005, (
                "DB final probs for '{}' sum to {:.6f}".format(lhs, total))
        conn.close()

    def test_iterations_monotonic_in_db(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT corpus_ll FROM iterations ORDER BY iteration")
        lls = [row[0] for row in c.fetchall()]
        conn.close()
        for i in range(1, len(lls)):
            assert lls[i] >= lls[i - 1] - 1e-4

    def test_iterations_match_json(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT corpus_ll FROM iterations ORDER BY iteration")
        db_lls = [row[0] for row in c.fetchall()]
        conn.close()
        assert len(db_lls) == len(output_20["iteration_lls"])
        for db_val, json_val in zip(db_lls, output_20["iteration_lls"]):
            assert abs(db_val - json_val) < 1e-6

    def test_final_probs_match_json(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT rule_id, final_prob FROM rules ORDER BY rule_id")
        db_probs = {row[0]: row[1] for row in c.fetchall()}
        conn.close()
        for idx, rule in enumerate(output_20["final_rules"]):
            assert abs(db_probs[idx] - rule[0]) < 1e-6


# ==================================================================
# SQLite Query Tests
# ==================================================================

class TestSQLiteQueries:
    def test_convergence_query(self, output_20):
        """Find iteration with biggest LL improvement."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("""
            SELECT a.iteration, a.corpus_ll - b.corpus_ll AS improvement
            FROM iterations a
            JOIN iterations b ON a.iteration = b.iteration + 1
            ORDER BY improvement DESC
            LIMIT 1
        """)
        row = c.fetchone()
        conn.close()
        assert row is not None
        assert row[0] >= 2
        assert row[1] > 0

    def test_rule_history_final_matches_rules(self, output_20):
        """Rule history at last iteration should match rules.final_prob."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("""
            SELECT r.rule_id, r.final_prob, rh.probability
            FROM rules r
            JOIN rule_history rh ON r.rule_id = rh.rule_id
            WHERE rh.iteration = (SELECT MAX(iteration) FROM iterations)
        """)
        for rule_id, final_prob, hist_prob in c.fetchall():
            assert abs(final_prob - hist_prob) < 1e-6, (
                "Rule {}: final={}, history={}".format(
                    rule_id, final_prob, hist_prob))
        conn.close()

    def test_unused_rule_history_decreasing(self, output_20):
        """NP -> N N initial_prob should be > final_prob (driven to ~0)."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("""
            SELECT initial_prob, final_prob
            FROM rules
            WHERE lhs = 'NP' AND rhs = 'N N'
        """)
        row = c.fetchone()
        conn.close()
        assert row is not None, "Rule NP -> N N not found"
        assert row[0] > row[1], (
            "initial_prob {} should be > final_prob {}".format(
                row[0], row[1]))
        assert row[1] < 0.01

    def test_sentence_ll_consistency_in_db(self, output_20):
        """Sentence LLs in DB should match JSON output."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute(
            "SELECT log_likelihood FROM sentence_parses "
            "ORDER BY sentence_id")
        db_lls = [row[0] for row in c.fetchall()]
        conn.close()
        for db_val, json_val in zip(db_lls, output_20["sentence_lls"]):
            assert abs(db_val - json_val) < 1e-4


# ==================================================================
# Viterbi Parse Tree Tests
# ==================================================================

class TestViterbiParses:
    def test_all_parses_present(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT viterbi_tree FROM sentence_parses")
        trees = [row[0] for row in c.fetchall()]
        conn.close()
        assert len(trees) == 8
        for tree in trees:
            assert tree and tree != 'NONE' and tree.startswith('(S ')

    def test_parse_leaves_match_sentences(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT sentence, viterbi_tree FROM sentence_parses")
        for sentence, tree in c.fetchall():
            words = sentence.split()
            leaves = extract_leaves(tree)
            assert leaves == words, (
                "Leaves {} != words {}".format(leaves, words))
        conn.close()

    def test_simple_sentence_parse(self, output_20):
        """'the dog saw the cat' is unambiguous."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute(
            "SELECT viterbi_tree FROM sentence_parses "
            "WHERE sentence_id = 0")
        tree = c.fetchone()[0]
        conn.close()
        expected = ("(S (NP (Det the) (N dog)) "
                    "(VP (V saw) (NP (Det the) (N cat))))")
        assert tree == expected, "Got: {}".format(tree)

    def test_second_sentence_parse(self, output_20):
        """'a cat ate the fish' is unambiguous."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute(
            "SELECT viterbi_tree FROM sentence_parses "
            "WHERE sentence_id = 1")
        tree = c.fetchone()[0]
        conn.close()
        expected = ("(S (NP (Det a) (N cat)) "
                    "(VP (V ate) (NP (Det the) (N fish))))")
        assert tree == expected, "Got: {}".format(tree)

    def test_vpp_sentence_parse(self, output_20):
        """'the dog ate in the park' only parses with VP -> V PP."""
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute(
            "SELECT viterbi_tree FROM sentence_parses "
            "WHERE sentence_id = 6")
        tree = c.fetchone()[0]
        conn.close()
        expected = ("(S (NP (Det the) (N dog)) "
                    "(VP (V ate) (PP (P in) (NP (Det the) (N park)))))")
        assert tree == expected, "Got: {}".format(tree)

    def test_balanced_parentheses(self, output_20):
        conn = sqlite3.connect('/app/grammar.db')
        c = conn.cursor()
        c.execute("SELECT viterbi_tree FROM sentence_parses")
        for (tree,) in c.fetchall():
            opens = tree.count('(')
            closes = tree.count(')')
            assert opens == closes, (
                "Unbalanced parens in: {}".format(tree[:100]))
        conn.close()


# ==================================================================
# SVG Parse Tree Tests
# ==================================================================

class TestParseTreeSVGs:
    def test_svg_files_exist(self, output_20):
        for i in range(8):
            path = '/app/trees/sentence_{}.svg'.format(i)
            assert os.path.exists(path), "Missing SVG: {}".format(path)

    def test_svg_files_valid(self, output_20):
        for i in range(8):
            path = '/app/trees/sentence_{}.svg'.format(i)
            with open(path) as f:
                content = f.read()
            assert '<svg' in content, (
                "{} missing <svg tag".format(path))
            assert '</svg>' in content, (
                "{} missing </svg> tag".format(path))

    def test_svg_files_nonempty(self, output_20):
        for i in range(8):
            path = '/app/trees/sentence_{}.svg'.format(i)
            size = os.path.getsize(path)
            assert size > 200, (
                "{} too small ({} bytes)".format(path, size))

    def test_dot_files_exist(self, output_20):
        for i in range(8):
            path = '/app/trees/sentence_{}.dot'.format(i)
            assert os.path.exists(path), "Missing DOT: {}".format(path)

    def test_dot_files_valid(self, output_20):
        for i in range(8):
            path = '/app/trees/sentence_{}.dot'.format(i)
            with open(path) as f:
                content = f.read()
            assert 'digraph' in content, (
                "{} not a valid DOT file".format(path))
            assert '->' in content, (
                "{} has no edges".format(path))
