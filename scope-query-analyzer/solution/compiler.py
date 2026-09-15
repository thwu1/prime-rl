#!/usr/bin/env python3
"""
Cursorless scope query compiler.

Parses Cursorless tree-sitter .scm query files, validates them using
tree-sitter Python bindings, performs semantic analysis of capture
naming conventions, and produces a comprehensive compiled scope report.

"""

import json
import re
from collections import defaultdict
from pathlib import Path

import tree_sitter_python as tspython
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser, Query, QueryCursor


QUERY_DIR = Path("/app/queries")
SAMPLE_DIR = Path("/app/samples")
OUTPUT_PATH = Path("/app/compiled_scopes.json")

LANG_CONFIG = {
    "python.scm": {
        "language": Language(tspython.language()),
        "sample": "python_sample.py",
    },
    "java.scm": {
        "language": Language(tsjava.language()),
        "sample": "java_sample.java",
    },
    "javascript.scm": {
        "language": Language(tsjs.language()),
        "sample": "javascript_sample.js",
    },
    "typescript.scm": {
        "language": Language(tsts.language_typescript()),
        "sample": "typescript_sample.ts",
    },
}


def extract_imports(text):
    imports = []
    for line in text.split("\n"):
        m = re.match(r"^\s*;;\s*import\s+(\S+\.scm)\s*$", line)
        if m:
            imports.append(m.group(1))
    return imports


def strip_comments(text):
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(";;"):
            continue
        result.append(line)
    return "\n".join(result)


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\n\r":
            i += 1
            continue
        if c == "(":
            tokens.append(("LPAREN", "("))
            i += 1
            continue
        if c == ")":
            tokens.append(("RPAREN", ")"))
            i += 1
            continue
        if c == "[":
            tokens.append(("LBRACKET", "["))
            i += 1
            continue
        if c == "]":
            tokens.append(("RBRACKET", "]"))
            i += 1
            continue
        if c == ".":
            tokens.append(("ANCHOR", "."))
            i += 1
            continue
        if c in "?*+":
            tokens.append(("QUANTIFIER", c))
            i += 1
            continue
        if c == "!":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(("NEGATION", text[i:j]))
            i = j
            continue
        if c == "@":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_."):
                j += 1
            tokens.append(("CAPTURE", text[i:j]))
            i = j
            continue
        if c == "#":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "-_!?"):
                j += 1
            tokens.append(("PREDICATE", text[i:j]))
            i = j
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            tokens.append(("STRING", text[i:j]))
            i = j
            continue
        if c == ":":
            tokens.append(("COLON", ":"))
            i += 1
            continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_.-"):
                j += 1
            val = text[i:j].rstrip(".-")
            tokens.append(("IDENTIFIER", val))
            i = i + len(val)
            continue
        i += 1
    return tokens


def analyze_tokens(tokens):
    captures = set()
    predicates = []
    node_types = set()
    for i, (tok_type, tok_val) in enumerate(tokens):
        if tok_type == "CAPTURE":
            captures.add(tok_val[1:])
        elif tok_type == "PREDICATE":
            predicates.append(tok_val)
        elif tok_type == "IDENTIFIER":
            if i + 1 < len(tokens) and tokens[i + 1][0] == "COLON":
                continue
            if tok_val == "_":
                continue
            for j in range(i - 1, -1, -1):
                prev_type = tokens[j][0]
                if prev_type == "LPAREN":
                    node_types.add(tok_val)
                    break
                elif prev_type == "ANCHOR":
                    continue
                else:
                    break
    return captures, predicates, node_types


def parse_captures(captures):
    scope_types = set()
    facets = defaultdict(set)
    for capture in captures:
        parts = capture.split(".")
        base = parts[0]
        if base.startswith("_"):
            continue
        scope_types.add(base)
        if len(parts) > 1:
            facets[base].add(parts[1])
    return scope_types, facets


def classify_predicates(all_predicates):
    filters = defaultdict(int)
    directives = defaultdict(int)
    for pred in all_predicates:
        if pred.endswith("?"):
            filters[pred] += 1
        elif pred.endswith("!"):
            directives[pred] += 1
    return dict(sorted(filters.items())), dict(sorted(directives.items()))


def validate_query(language, cleaned_text):
    try:
        q = Query(language, cleaned_text)
        return {
            "valid": True,
            "pattern_count": q.pattern_count,
            "capture_count": q.capture_count,
        }
    except Exception:
        return {
            "valid": False,
            "pattern_count": 0,
            "capture_count": 0,
        }


def execute_query(language, cleaned_text, sample_path):
    q = Query(language, cleaned_text)
    parser = Parser(language)
    with open(sample_path, "rb") as f:
        source = f.read()
    tree = parser.parse(source)
    cursor = QueryCursor(q)
    captures = cursor.captures(tree.root_node)

    total = sum(len(nodes) for nodes in captures.values())
    unique = len(captures)

    scope_types = set()
    for cap_name in captures.keys():
        base = cap_name.split(".")[0]
        if not base.startswith("_"):
            scope_types.add(base)

    return {
        "total_capture_hits": total,
        "unique_captures_matched": unique,
        "scope_types_matched": sorted(scope_types),
    }


def main():
    filenames = sorted(f.name for f in QUERY_DIR.glob("*.scm"))

    report = {
        "query_validation": {},
        "imports": {},
        "scope_types": {},
        "facets": {},
        "predicates": {},
        "node_types": {},
        "cross_language_matrix": {},
        "execution_results": {},
    }

    all_predicates = []
    all_scope_types = defaultdict(list)  # scope_type -> [files]

    for fname in filenames:
        filepath = QUERY_DIR / fname
        with open(filepath) as f:
            text = f.read()

        # Static analysis
        file_imports = extract_imports(text)
        cleaned = strip_comments(text)
        tokens = tokenize(cleaned)
        captures, predicates, node_types = analyze_tokens(tokens)
        scope_types_set, facets_dict = parse_captures(captures)

        report["imports"][fname] = file_imports
        report["scope_types"][fname] = sorted(scope_types_set)
        report["facets"][fname] = {k: sorted(v) for k, v in sorted(facets_dict.items())}
        report["node_types"][fname] = sorted(node_types)

        all_predicates.extend(predicates)
        for st in scope_types_set:
            all_scope_types[st].append(fname)

        # Tree-sitter validation
        cfg = LANG_CONFIG[fname]
        report["query_validation"][fname] = validate_query(cfg["language"], cleaned)

        # Query execution against sample code
        sample_path = SAMPLE_DIR / cfg["sample"]
        report["execution_results"][fname] = execute_query(
            cfg["language"], cleaned, sample_path
        )

    # Predicate classification
    filters, directives = classify_predicates(all_predicates)
    report["predicates"] = {"filters": filters, "directives": directives}

    # Cross-language matrix
    report["cross_language_matrix"] = {
        st: sorted(files) for st, files in sorted(all_scope_types.items())
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Compiled scopes written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
