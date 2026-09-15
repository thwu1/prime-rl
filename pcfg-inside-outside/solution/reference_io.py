#!/usr/bin/env python3
"""

Inside-Outside Algorithm for PCFG Parameter Estimation via EM.
Implements CYK-based inside/outside dynamic programming and
expectation-maximization for learning rule probabilities.
"""

import json
import math
import sys
import argparse
from collections import defaultdict


def parse_grammar(filepath):
    """Parse a CNF PCFG grammar file. Returns list of rules and set of nonterminals."""
    rules = []
    nonterminals = set()
    with open(filepath) as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            prob = float(parts[0])
            lhs = parts[1]
            rhs = tuple(parts[2].split())
            rules.append([prob, lhs, rhs])
            nonterminals.add(lhs)
    return rules, nonterminals


def parse_corpus(filepath):
    """Parse corpus file. Returns list of word lists."""
    sentences = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                sentences.append(line.split())
    return sentences


def compute_inside(words, rules, nonterminals):
    """CYK inside algorithm.
    Returns table where table[i][j][A] = P(A =>* w_i ... w_j).
    """
    n = len(words)
    table = [[defaultdict(float) for _ in range(n)] for _ in range(n)]

    # Base case: terminal (lexical) rules
    for i in range(n):
        for rule in rules:
            prob, lhs, rhs = rule
            if len(rhs) == 1 and rhs[0] == words[i]:
                table[i][i][lhs] += prob

    # Recursive case: binary rules, increasing span length
    for span_len in range(2, n + 1):
        for i in range(n - span_len + 1):
            j = i + span_len - 1
            for k in range(i, j):
                for rule in rules:
                    prob, lhs, rhs = rule
                    if len(rhs) == 2:
                        B, C = rhs
                        ib = table[i][k].get(B, 0.0)
                        ic = table[k + 1][j].get(C, 0.0)
                        if ib > 0 and ic > 0:
                            table[i][j][lhs] += prob * ib * ic

    return table


def compute_outside(words, rules, nonterminals, inside_table, start_symbol):
    """CYK outside algorithm.
    Returns table where table[i][j][A] = outside probability of A spanning (i,j).
    Must be computed top-down (large spans before small spans).
    """
    n = len(words)
    table = [[defaultdict(float) for _ in range(n)] for _ in range(n)]

    # Base case: start symbol spanning entire sentence
    table[0][n - 1][start_symbol] = 1.0

    # Top-down: decreasing span length
    for span_len in range(n, 0, -1):
        for i in range(n - span_len + 1):
            j = i + span_len - 1
            # For each rule lhs -> B C that could use span (i,j) as the parent:
            for rule in rules:
                prob, lhs, rhs = rule
                if len(rhs) == 2:
                    B, C = rhs
                    out_lhs = table[i][j].get(lhs, 0.0)
                    if out_lhs <= 0:
                        continue
                    for k in range(i, j):
                        # lhs spans (i,j), B spans (i,k), C spans (k+1,j)
                        ib = inside_table[i][k].get(B, 0.0)
                        ic = inside_table[k + 1][j].get(C, 0.0)
                        if ic > 0:
                            table[i][k][B] += out_lhs * prob * ic
                        if ib > 0:
                            table[k + 1][j][C] += out_lhs * prob * ib

    return table


def em_iteration(sentences, rules, nonterminals, start_symbol):
    """One EM iteration: E-step (compute expected counts) + M-step (normalize).
    Returns (new_rules, old_ll) where old_ll is the LL under the current grammar.
    """
    expected_counts = defaultdict(float)
    lhs_totals = defaultdict(float)
    total_ll = 0.0

    for words in sentences:
        n = len(words)
        inside_table = compute_inside(words, rules, nonterminals)
        sentence_prob = inside_table[0][n - 1].get(start_symbol, 0.0)

        if sentence_prob <= 0:
            total_ll = float('-inf')
            continue

        total_ll += math.log(sentence_prob)
        outside_table = compute_outside(words, rules, nonterminals, inside_table, start_symbol)

        for idx, rule in enumerate(rules):
            prob, lhs, rhs = rule
            if prob <= 0:
                continue
            if len(rhs) == 1:
                # Terminal rule: accumulate expected count
                terminal = rhs[0]
                for i in range(n):
                    if words[i] == terminal:
                        out_val = outside_table[i][i].get(lhs, 0.0)
                        if out_val > 0:
                            count = out_val * prob / sentence_prob
                            expected_counts[idx] += count
                            lhs_totals[lhs] += count
            else:
                # Binary rule
                B, C = rhs
                for i in range(n):
                    for j in range(i + 1, n):
                        out_val = outside_table[i][j].get(lhs, 0.0)
                        if out_val <= 0:
                            continue
                        for k in range(i, j):
                            ib = inside_table[i][k].get(B, 0.0)
                            ic = inside_table[k + 1][j].get(C, 0.0)
                            if ib > 0 and ic > 0:
                                count = out_val * prob * ib * ic / sentence_prob
                                expected_counts[idx] += count
                                lhs_totals[lhs] += count

    # M-step: normalize expected counts
    new_rules = []
    for idx, rule in enumerate(rules):
        prob, lhs, rhs = rule
        if lhs_totals[lhs] > 0:
            new_prob = expected_counts[idx] / lhs_totals[lhs]
        else:
            new_prob = prob  # keep old probability if no evidence
        new_rules.append([new_prob, lhs, rhs])

    return new_rules, total_ll


def compute_corpus_ll(sentences, rules, nonterminals, start_symbol):
    """Compute total and per-sentence log-likelihoods."""
    total_ll = 0.0
    sentence_lls = []
    for words in sentences:
        n = len(words)
        inside_table = compute_inside(words, rules, nonterminals)
        prob = inside_table[0][n - 1].get(start_symbol, 0.0)
        if prob > 0:
            ll = math.log(prob)
        else:
            ll = float('-inf')
        sentence_lls.append(ll)
        total_ll += ll
    return total_ll, sentence_lls


def main():
    parser = argparse.ArgumentParser(
        description='Inside-Outside EM for PCFG parameter estimation')
    parser.add_argument('--grammar', required=True, help='Path to grammar file')
    parser.add_argument('--corpus', required=True, help='Path to corpus file')
    parser.add_argument('--iterations', type=int, default=20,
                        help='Number of EM iterations')
    args = parser.parse_args()

    rules, nonterminals = parse_grammar(args.grammar)
    sentences = parse_corpus(args.corpus)
    start_symbol = rules[0][1]  # LHS of first rule

    # Compute initial log-likelihood
    initial_ll, _ = compute_corpus_ll(sentences, rules, nonterminals, start_symbol)

    # Run EM iterations
    iteration_lls = []
    for i in range(args.iterations):
        rules, _old_ll = em_iteration(sentences, rules, nonterminals, start_symbol)
        new_ll, _ = compute_corpus_ll(sentences, rules, nonterminals, start_symbol)
        iteration_lls.append(new_ll)

    # Compute final per-sentence log-likelihoods
    _, sentence_lls = compute_corpus_ll(sentences, rules, nonterminals, start_symbol)

    result = {
        "initial_ll": initial_ll,
        "iteration_lls": iteration_lls,
        "final_rules": [[r[0], r[1], list(r[2])] for r in rules],
        "sentence_lls": sentence_lls
    }

    print(json.dumps(result))


if __name__ == '__main__':
    main()
