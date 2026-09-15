#!/usr/bin/env python3
"""
Probabilistic Parser with evaluation and visualization.
"""
import math
import re
from collections import defaultdict


class Grammar:
    def __init__(self):
        self.rules = []
        self.lexicon = []
        self.binary_idx = None
        self.unary_idx = None
        self.lex_idx = None
        self.artificial_nts = set()
        self.start_symbol = 'S'

    @staticmethod
    def from_file(filepath):
        g = Grammar()
        mode = None
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line == 'Grammar':
                    mode = 'grammar'
                    continue
                if line == 'Lexicon':
                    mode = 'lexicon'
                    continue
                parts = line.split()
                prob = float(parts[0])
                rule_str = ' '.join(parts[1:])
                lhs, rhs_str = rule_str.split('->')
                lhs = lhs.strip()
                if mode == 'grammar':
                    rhs = rhs_str.strip().split()
                    g.rules.append((prob, lhs, rhs))
                elif mode == 'lexicon':
                    word = rhs_str.strip()
                    g.lexicon.append((prob, lhs, word))
        g._binarize()
        g._build_indices()
        return g

    def _binarize(self):
        new_rules = []
        counter = 0
        for prob, lhs, rhs in self.rules:
            if len(rhs) <= 2:
                new_rules.append((prob, lhs, rhs))
            else:
                symbols = list(rhs)
                current_lhs = lhs
                current_prob = prob
                while len(symbols) > 2:
                    new_nt = '@{}_{}'.format(lhs, counter)
                    counter += 1
                    self.artificial_nts.add(new_nt)
                    new_rules.append((current_prob, current_lhs, [symbols[0], new_nt]))
                    current_lhs = new_nt
                    current_prob = 1.0
                    symbols = symbols[1:]
                new_rules.append((current_prob, current_lhs, symbols))
        self.rules = new_rules

    def _build_indices(self):
        self.binary_idx = defaultdict(list)
        self.unary_idx = defaultdict(list)
        self.lex_idx = defaultdict(list)
        for prob, lhs, rhs in self.rules:
            if len(rhs) == 2:
                self.binary_idx[(rhs[0], rhs[1])].append((lhs, prob))
            elif len(rhs) == 1:
                self.unary_idx[rhs[0]].append((lhs, prob))
        for prob, pos, word in self.lexicon:
            self.lex_idx[word].append((pos, prob))


def parse_sentence(grammar, sentence):
    words = sentence.split()
    n = len(words)

    vit = [[{} for _ in range(n)] for _ in range(n)]
    back = [[{} for _ in range(n)] for _ in range(n)]
    ins = [[defaultdict(float) for _ in range(n)] for _ in range(n)]

    for j in range(n):
        word = words[j]
        for pos, prob in grammar.lex_idx[word]:
            if pos not in vit[j][j] or prob > vit[j][j][pos]:
                vit[j][j][pos] = prob
                back[j][j][pos] = ('lex', word)
            ins[j][j][pos] += prob
        _unary_close(grammar, vit, back, ins, j, j)

    for span in range(2, n + 1):
        for i in range(n - span + 1):
            j = i + span - 1
            for k in range(i, j):
                left_nts_v = list(vit[i][k].keys())
                right_nts_v = list(vit[k + 1][j].keys())
                for left_nt in left_nts_v:
                    for right_nt in right_nts_v:
                        key = (left_nt, right_nt)
                        if key in grammar.binary_idx:
                            for parent_nt, rule_prob in grammar.binary_idx[key]:
                                new_prob = rule_prob * vit[i][k][left_nt] * vit[k + 1][j][right_nt]
                                if parent_nt not in vit[i][j] or new_prob > vit[i][j][parent_nt]:
                                    vit[i][j][parent_nt] = new_prob
                                    back[i][j][parent_nt] = ('binary', k, left_nt, right_nt)

                left_nts_i = list(ins[i][k].keys())
                right_nts_i = list(ins[k + 1][j].keys())
                for left_nt in left_nts_i:
                    for right_nt in right_nts_i:
                        key = (left_nt, right_nt)
                        if key in grammar.binary_idx:
                            for parent_nt, rule_prob in grammar.binary_idx[key]:
                                ins[i][j][parent_nt] += rule_prob * ins[i][k][left_nt] * ins[k + 1][j][right_nt]

            _unary_close(grammar, vit, back, ins, i, j)

    start = grammar.start_symbol
    accepted = start in vit[0][n - 1]
    best_prob = vit[0][n - 1].get(start, 0.0)
    total_prob = ins[0][n - 1].get(start, 0.0)

    best_parse = None
    if accepted:
        raw_tree = _extract_tree(back, 0, n - 1, start, words)
        db_tree = _debinarize(raw_tree, grammar.artificial_nts)
        best_parse = tree_to_sexpr(db_tree)

    return {
        'accepted': accepted,
        'best_parse': best_parse,
        'best_prob': best_prob,
        'total_prob': total_prob,
    }


def _unary_close(grammar, vit, back, ins, i, j):
    changed = True
    while changed:
        changed = False
        for child_nt in list(vit[i][j].keys()):
            for parent_nt, rule_prob in grammar.unary_idx[child_nt]:
                new_prob = rule_prob * vit[i][j][child_nt]
                if parent_nt not in vit[i][j] or new_prob > vit[i][j][parent_nt]:
                    vit[i][j][parent_nt] = new_prob
                    back[i][j][parent_nt] = ('unary', child_nt)
                    changed = True

    base = dict(ins[i][j])
    for _ in range(20):
        new_vals = dict(base)
        for child_nt in ins[i][j]:
            child_val = ins[i][j][child_nt]
            for parent_nt, rule_prob in grammar.unary_idx[child_nt]:
                if parent_nt not in new_vals:
                    new_vals[parent_nt] = 0.0
                new_vals[parent_nt] += rule_prob * child_val
        converged = True
        for k in set(new_vals.keys()) | set(ins[i][j].keys()):
            if abs(new_vals.get(k, 0.0) - ins[i][j].get(k, 0.0)) > 1e-15:
                converged = False
                break
        ins[i][j] = defaultdict(float, new_vals)
        if converged:
            break


def _extract_tree(back, i, j, nt, words):
    bp = back[i][j][nt]
    if bp[0] == 'lex':
        return (nt, bp[1])
    elif bp[0] == 'unary':
        child_nt = bp[1]
        child_tree = _extract_tree(back, i, j, child_nt, words)
        return (nt, child_tree)
    elif bp[0] == 'binary':
        k, left_nt, right_nt = bp[1], bp[2], bp[3]
        left_tree = _extract_tree(back, i, k, left_nt, words)
        right_tree = _extract_tree(back, k + 1, j, right_nt, words)
        return (nt, left_tree, right_tree)


def _debinarize(tree, artificial_nts):
    if isinstance(tree, str):
        return tree
    if len(tree) == 2 and isinstance(tree[1], str):
        return tree

    children = []
    for child in tree[1:]:
        db_child = _debinarize(child, artificial_nts)
        if isinstance(db_child, tuple) and db_child[0] in artificial_nts:
            children.extend(db_child[1:])
        else:
            children.append(db_child)
    return (tree[0],) + tuple(children)


def tree_to_sexpr(tree):
    if isinstance(tree, str):
        return tree
    if len(tree) == 2 and isinstance(tree[1], str):
        return '[{} {}]'.format(tree[0], tree[1])
    children_str = ' '.join(tree_to_sexpr(child) for child in tree[1:])
    return '[{} {}]'.format(tree[0], children_str)


def parse_sexpr(s):
    s = s.strip()
    if not s.startswith('['):
        return s
    s = s[1:-1].strip()
    parts = s.split(None, 1)
    label = parts[0]
    if len(parts) == 1:
        return (label,)
    rest = parts[1]
    children = []
    idx = 0
    while idx < len(rest):
        if rest[idx] == '[':
            depth = 1
            j = idx + 1
            while depth > 0:
                if rest[j] == '[':
                    depth += 1
                elif rest[j] == ']':
                    depth -= 1
                j += 1
            children.append(parse_sexpr(rest[idx:j]))
            idx = j
        elif rest[idx].isspace():
            idx += 1
        else:
            j = idx
            while j < len(rest) and not rest[j].isspace() and rest[j] != '[':
                j += 1
            children.append(rest[idx:j])
            idx = j
    return (label,) + tuple(children)


def _get_spans(tree, start=0):
    spans = set()
    if len(tree) == 2 and isinstance(tree[1], str):
        return spans, start + 1
    pos = start
    for child in tree[1:]:
        child_spans, pos = _get_spans(child, pos)
        spans |= child_spans
    spans.add((tree[0], start, pos))
    return spans, pos


def labeled_precision_recall(predicted_sexpr, gold_sexpr):
    pred_tree = parse_sexpr(predicted_sexpr)
    gold_tree = parse_sexpr(gold_sexpr)
    pred_spans, _ = _get_spans(pred_tree)
    gold_spans, _ = _get_spans(gold_tree)
    if not pred_spans or not gold_spans:
        return (0.0, 0.0)
    common = pred_spans & gold_spans
    precision = len(common) / len(pred_spans)
    recall = len(common) / len(gold_spans)
    return (precision, recall)


def tree_to_dot(sexpr_str):
    """Convert bracket notation parse tree to Graphviz DOT format."""
    tree = parse_sexpr(sexpr_str)
    lines = ['digraph parse_tree {', '  rankdir=TB;', '  node [shape=box];']
    counter = [0]

    def _traverse(node, parent_id=None):
        nid = counter[0]
        counter[0] += 1

        if isinstance(node, str):
            lines.append('  n{} [label="{}" shape=ellipse];'.format(nid, node))
            if parent_id is not None:
                lines.append('  n{} -> n{};'.format(parent_id, nid))
            return

        label = node[0]
        lines.append('  n{} [label="{}"];'.format(nid, label))
        if parent_id is not None:
            lines.append('  n{} -> n{};'.format(parent_id, nid))

        for child in node[1:]:
            _traverse(child, nid)

    _traverse(tree)
    lines.append('}')
    return '\n'.join(lines)
