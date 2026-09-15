#!/usr/bin/env python3
"""

PCFG Grammar Induction Pipeline - Core Implementation
Inside-Outside EM + Viterbi CYK + SQLite + Graphviz DOT generation
"""

import json
import math
import sys
import argparse
import sqlite3
import os
from collections import defaultdict


def parse_grammar(filepath):
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
    sentences = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                sentences.append(line.split())
    return sentences


def compute_inside(words, rules, nonterminals):
    n = len(words)
    table = [[defaultdict(float) for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for rule in rules:
            prob, lhs, rhs = rule
            if len(rhs) == 1 and rhs[0] == words[i]:
                table[i][i][lhs] += prob
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
    n = len(words)
    table = [[defaultdict(float) for _ in range(n)] for _ in range(n)]
    table[0][n - 1][start_symbol] = 1.0
    for span_len in range(n, 0, -1):
        for i in range(n - span_len + 1):
            j = i + span_len - 1
            for rule in rules:
                prob, lhs, rhs = rule
                if len(rhs) == 2:
                    B, C = rhs
                    out_lhs = table[i][j].get(lhs, 0.0)
                    if out_lhs <= 0:
                        continue
                    for k in range(i, j):
                        ib = inside_table[i][k].get(B, 0.0)
                        ic = inside_table[k + 1][j].get(C, 0.0)
                        if ic > 0:
                            table[i][k][B] += out_lhs * prob * ic
                        if ib > 0:
                            table[k + 1][j][C] += out_lhs * prob * ib
    return table


def em_iteration(sentences, rules, nonterminals, start_symbol):
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
        outside_table = compute_outside(words, rules, nonterminals,
                                        inside_table, start_symbol)
        for idx, rule in enumerate(rules):
            prob, lhs, rhs = rule
            if prob <= 0:
                continue
            if len(rhs) == 1:
                terminal = rhs[0]
                for i in range(n):
                    if words[i] == terminal:
                        out_val = outside_table[i][i].get(lhs, 0.0)
                        if out_val > 0:
                            count = out_val * prob / sentence_prob
                            expected_counts[idx] += count
                            lhs_totals[lhs] += count
            else:
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
                                count = (out_val * prob * ib * ic
                                         / sentence_prob)
                                expected_counts[idx] += count
                                lhs_totals[lhs] += count
    new_rules = []
    for idx, rule in enumerate(rules):
        prob, lhs, rhs = rule
        if lhs_totals[lhs] > 0:
            new_prob = expected_counts[idx] / lhs_totals[lhs]
        else:
            new_prob = prob
        new_rules.append([new_prob, lhs, rhs])
    return new_rules, total_ll


def compute_corpus_ll(sentences, rules, nonterminals, start_symbol):
    total_ll = 0.0
    sentence_lls = []
    for words in sentences:
        n = len(words)
        inside_table = compute_inside(words, rules, nonterminals)
        prob = inside_table[0][n - 1].get(start_symbol, 0.0)
        ll = math.log(prob) if prob > 0 else float('-inf')
        sentence_lls.append(ll)
        total_ll += ll
    return total_ll, sentence_lls


def viterbi_parse(words, rules, nonterminals, start_symbol):
    n = len(words)
    # table[i][j][A] = (max_prob, backpointer)
    table = [[{} for _ in range(n)] for _ in range(n)]

    for i in range(n):
        for rule in rules:
            prob, lhs, rhs = rule
            if len(rhs) == 1 and rhs[0] == words[i]:
                if lhs not in table[i][i] or prob > table[i][i][lhs][0]:
                    table[i][i][lhs] = (prob, ('term', words[i]))

    for span_len in range(2, n + 1):
        for i in range(n - span_len + 1):
            j = i + span_len - 1
            for k in range(i, j):
                for rule in rules:
                    prob, lhs, rhs = rule
                    if len(rhs) == 2:
                        B, C = rhs
                        if B in table[i][k] and C in table[k + 1][j]:
                            p = prob * table[i][k][B][0] * table[k + 1][j][C][0]
                            if lhs not in table[i][j] or p > table[i][j][lhs][0]:
                                table[i][j][lhs] = (p, ('bin', B, C, k))

    if start_symbol not in table[0][n - 1]:
        return None

    def extract(sym, i, j):
        _, bp = table[i][j][sym]
        if bp[0] == 'term':
            return "({} {})".format(sym, bp[1])
        else:
            _, B, C, k = bp
            return "({} {} {})".format(sym, extract(B, i, k),
                                       extract(C, k + 1, j))

    return extract(start_symbol, 0, n - 1)


def tree_to_dot(tree_str):
    counter = [0]
    lines = ['digraph G {',
             '  rankdir=TB;',
             '  node [shape=plaintext fontname="Helvetica"];']

    def next_id():
        counter[0] += 1
        return 'n{}'.format(counter[0])

    def parse_emit(s, pos):
        while pos < len(s) and s[pos] == ' ':
            pos += 1
        if pos >= len(s):
            return None, pos
        if s[pos] == '(':
            pos += 1
            end = pos
            while end < len(s) and s[end] not in ' )':
                end += 1
            label = s[pos:end]
            pos = end
            my_id = next_id()
            lines.append('  {} [label="{}"];'.format(my_id, label))
            while pos < len(s) and s[pos] != ')':
                if s[pos] == ' ':
                    pos += 1
                    continue
                child_id, pos = parse_emit(s, pos)
                if child_id:
                    lines.append('  {} -> {};'.format(my_id, child_id))
            if pos < len(s):
                pos += 1
            return my_id, pos
        else:
            end = pos
            while end < len(s) and s[end] not in ' )':
                end += 1
            word = s[pos:end]
            my_id = next_id()
            lines.append('  {} [label="{}" shape=box];'.format(my_id, word))
            return my_id, end

    parse_emit(tree_str, 0)
    lines.append('}')
    return '\n'.join(lines)


def create_database(db_path, initial_rules, final_rules, iteration_lls,
                    rule_history, sentences, sentence_lls, viterbi_trees):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('CREATE TABLE rules ('
              'rule_id INTEGER PRIMARY KEY, '
              'lhs TEXT NOT NULL, '
              'rhs TEXT NOT NULL, '
              'initial_prob REAL NOT NULL, '
              'final_prob REAL NOT NULL)')

    c.execute('CREATE TABLE iterations ('
              'iteration INTEGER PRIMARY KEY, '
              'corpus_ll REAL NOT NULL)')

    c.execute('CREATE TABLE rule_history ('
              'rule_id INTEGER NOT NULL, '
              'iteration INTEGER NOT NULL, '
              'probability REAL NOT NULL, '
              'PRIMARY KEY (rule_id, iteration))')

    c.execute('CREATE TABLE sentence_parses ('
              'sentence_id INTEGER PRIMARY KEY, '
              'sentence TEXT NOT NULL, '
              'log_likelihood REAL NOT NULL, '
              'viterbi_tree TEXT NOT NULL)')

    for idx in range(len(initial_rules)):
        rhs_str = ' '.join(initial_rules[idx][2])
        c.execute('INSERT INTO rules VALUES (?,?,?,?,?)',
                  (idx, initial_rules[idx][1], rhs_str,
                   initial_rules[idx][0], final_rules[idx][0]))

    for i, ll in enumerate(iteration_lls):
        c.execute('INSERT INTO iterations VALUES (?,?)', (i + 1, ll))

    for rule_id, iteration, prob in rule_history:
        c.execute('INSERT INTO rule_history VALUES (?,?,?)',
                  (rule_id, iteration, prob))

    for i in range(len(sentences)):
        tree = viterbi_trees[i] if viterbi_trees[i] else 'NONE'
        c.execute('INSERT INTO sentence_parses VALUES (?,?,?,?)',
                  (i, ' '.join(sentences[i]), sentence_lls[i], tree))

    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--grammar', required=True)
    parser.add_argument('--corpus', required=True)
    parser.add_argument('--iterations', type=int, default=20)
    parser.add_argument('--db', default='/app/grammar.db')
    parser.add_argument('--treedir', default='/app/trees')
    args = parser.parse_args()

    rules, nonterminals = parse_grammar(args.grammar)
    sentences = parse_corpus(args.corpus)
    start_symbol = rules[0][1]

    initial_rules = [[r[0], r[1], r[2]] for r in rules]
    initial_ll, _ = compute_corpus_ll(sentences, rules, nonterminals,
                                       start_symbol)

    iteration_lls = []
    rule_history = []

    for it in range(args.iterations):
        rules, _ = em_iteration(sentences, rules, nonterminals, start_symbol)
        new_ll, _ = compute_corpus_ll(sentences, rules, nonterminals,
                                       start_symbol)
        iteration_lls.append(new_ll)
        for idx, rule in enumerate(rules):
            rule_history.append((idx, it + 1, rule[0]))

    _, sentence_lls = compute_corpus_ll(sentences, rules, nonterminals,
                                         start_symbol)

    viterbi_trees = []
    for words in sentences:
        tree = viterbi_parse(words, rules, nonterminals, start_symbol)
        viterbi_trees.append(tree)

    result = {
        "initial_ll": initial_ll,
        "iteration_lls": iteration_lls,
        "final_rules": [[r[0], r[1], list(r[2])] for r in rules],
        "sentence_lls": sentence_lls
    }
    print(json.dumps(result))

    create_database(args.db, initial_rules, rules, iteration_lls,
                    rule_history, sentences, sentence_lls, viterbi_trees)

    os.makedirs(args.treedir, exist_ok=True)
    for i, tree in enumerate(viterbi_trees):
        if tree:
            dot_content = tree_to_dot(tree)
            dot_path = os.path.join(args.treedir,
                                    'sentence_{}.dot'.format(i))
            with open(dot_path, 'w') as f:
                f.write(dot_content)


if __name__ == '__main__':
    main()
