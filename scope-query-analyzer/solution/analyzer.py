#!/usr/bin/env python3
"""
Cursorless tree-sitter query (.scm) scope analyzer.

Parses Cursorless-extended tree-sitter query files and produces a
structured JSON report of scope types, facets, predicates, imports,
and node types.

"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


def extract_imports(text):
    """Extract import directives from ;; import <file> comments."""
    imports = []
    for line in text.split('\n'):
        m = re.match(r'^\s*;;\s*import\s+(\S+\.scm)\s*$', line)
        if m:
            imports.append(m.group(1))
    return imports


def strip_comments(text):
    """Remove all ;; line comments from the text, respecting string literals."""
    lines = text.split('\n')
    result = []
    for line in lines:
        in_string = False
        i = 0
        comment_pos = None
        while i < len(line):
            ch = line[i]
            if ch == '"' and (i == 0 or line[i - 1] != '\\'):
                in_string = not in_string
            elif not in_string and ch == ';' and i + 1 < len(line) and line[i + 1] == ';':
                comment_pos = i
                break
            i += 1
        if comment_pos is not None:
            result.append(line[:comment_pos])
        else:
            result.append(line)
    return '\n'.join(result)


def tokenize(text):
    """
    Tokenize cleaned .scm text into a list of (type, value) tokens.

    Token types:
      LPAREN, RPAREN, LBRACKET, RBRACKET, ANCHOR, QUANTIFIER,
      NEGATION, CAPTURE, PREDICATE, STRING, COLON, IDENTIFIER
    """
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]

        # Whitespace
        if c in ' \t\n\r':
            i += 1
            continue

        # Brackets
        if c == '(':
            tokens.append(('LPAREN', '('))
            i += 1
            continue
        if c == ')':
            tokens.append(('RPAREN', ')'))
            i += 1
            continue
        if c == '[':
            tokens.append(('LBRACKET', '['))
            i += 1
            continue
        if c == ']':
            tokens.append(('RBRACKET', ']'))
            i += 1
            continue

        # Anchor
        if c == '.':
            tokens.append(('ANCHOR', '.'))
            i += 1
            continue

        # Quantifiers
        if c in '?*+':
            tokens.append(('QUANTIFIER', c))
            i += 1
            continue

        # Negation (e.g., !name)
        if c == '!':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            tokens.append(('NEGATION', text[i:j]))
            i = j
            continue

        # Capture (e.g., @name.domain.start.endOf)
        if c == '@':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in '_.'):
                j += 1
            tokens.append(('CAPTURE', text[i:j]))
            i = j
            continue

        # Predicate (e.g., #not-parent-type?)
        if c == '#':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in '-_!?'):
                j += 1
            tokens.append(('PREDICATE', text[i:j]))
            i = j
            continue

        # String literal
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\' and j + 1 < n:
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            tokens.append(('STRING', text[i:j]))
            i = j
            continue

        # Colon
        if c == ':':
            tokens.append(('COLON', ':'))
            i += 1
            continue

        # Identifier (node type, field name, or predicate argument)
        if c.isalpha() or c == '_':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in '_.-'):
                j += 1
            # Trim trailing dots/dashes that aren't part of identifiers
            val = text[i:j].rstrip('.-')
            tokens.append(('IDENTIFIER', val))
            i = i + len(val)
            continue

        # Skip any other character
        i += 1

    return tokens


def analyze_tokens(tokens):
    """
    Analyze a token stream to extract captures, predicates, and node types.

    Returns (captures_set, predicates_list, node_types_set).
    """
    captures = set()
    predicates = []
    node_types = set()

    for i, (tok_type, tok_val) in enumerate(tokens):
        if tok_type == 'CAPTURE':
            # Remove leading @
            captures.add(tok_val[1:])

        elif tok_type == 'PREDICATE':
            predicates.append(tok_val)

        elif tok_type == 'IDENTIFIER':
            # A named node type is an identifier that immediately follows LPAREN.
            # But NOT if followed by COLON (that makes it a field name).
            # Also skip wildcard '_'.
            if i + 1 < len(tokens) and tokens[i + 1][0] == 'COLON':
                continue  # field name, not node type

            if tok_val == '_':
                continue  # wildcard

            # Check if preceded by LPAREN (possibly with ANCHOR between)
            for j in range(i - 1, -1, -1):
                prev_type = tokens[j][0]
                if prev_type == 'LPAREN':
                    node_types.add(tok_val)
                    break
                elif prev_type == 'ANCHOR':
                    # Anchors can appear between ( and the identifier
                    continue
                else:
                    break

    return captures, predicates, node_types


def parse_captures(captures):
    """
    Parse capture names into scope types and facets.

    Returns (scope_types_set, facets_dict).
    facets_dict maps scope_type -> set of facet names.
    """
    scope_types = set()
    facets = defaultdict(set)

    for capture in captures:
        parts = capture.split('.')
        base = parts[0]

        # Skip private captures (base starts with _)
        if base.startswith('_'):
            continue

        scope_types.add(base)

        if len(parts) > 1:
            facets[base].add(parts[1])

    return scope_types, facets


def analyze_file(filepath):
    """Analyze a single .scm file and return its analysis dict."""
    with open(filepath) as f:
        text = f.read()

    imports = extract_imports(text)
    cleaned = strip_comments(text)
    tokens = tokenize(cleaned)
    captures, predicates, node_types = analyze_tokens(tokens)
    scope_types, facets = parse_captures(captures)

    return {
        'imports': imports,
        'scope_types': sorted(scope_types),
        'facets': {k: sorted(v) for k, v in sorted(facets.items())},
        'predicates': predicates,
        'node_types': sorted(node_types),
    }


def main():
    query_dir = Path('/app/queries')
    filenames = sorted(f.name for f in query_dir.glob('*.scm'))

    report = {
        'imports': {},
        'scope_types': {},
        'facets': {},
        'predicates': {},
        'node_types': {},
    }

    predicate_counts = defaultdict(int)

    for fname in filenames:
        filepath = query_dir / fname
        analysis = analyze_file(filepath)

        report['imports'][fname] = analysis['imports']
        report['scope_types'][fname] = analysis['scope_types']
        report['facets'][fname] = analysis['facets']
        report['node_types'][fname] = analysis['node_types']

        for pred in analysis['predicates']:
            predicate_counts[pred] += 1

    report['predicates'] = dict(sorted(predicate_counts.items()))

    output_path = Path('/app/analysis_report.json')
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Analysis report written to {output_path}")
    print(f"Files analyzed: {filenames}")
    print(f"Total predicates found: {sum(predicate_counts.values())}")


if __name__ == '__main__':
    main()
