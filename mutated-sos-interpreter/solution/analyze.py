#!/usr/bin/env python3
"""Analyze SOS rules to extract operator mutation mappings.

Reads the formal SOS rules file and identifies how each syntax operator
maps to its actual computational behavior by inspecting computation rules
(rules where both operands are fully evaluated values).
"""

import json
import os
import re


def parse_sos_rules(filepath):
    """Parse the SOS rules and extract operator mutation mappings.

    Returns (arith_map, comp_map, logic_map, unary_map) where each maps
    a syntax operator string to the actual operation it computes.
    """
    with open(filepath, encoding='utf-8') as f:
        content = f.read()

    rule_pattern = re.compile(r'Rule\s+(\d+)\s*:=\s*\{([^}]*)\}', re.DOTALL)
    rules = [
        (int(m.group(1)), m.group(2))
        for m in rule_pattern.finditer(content)
    ]

    arith_map = {}
    comp_map = {}
    logic_map = {}
    unary_map = {}

    for _num, body in rules:
        parts = re.split(r'-{3,}', body, maxsplit=1)
        if len(parts) == 2:
            premise, conclusion = parts[0].strip(), parts[1].strip()
        else:
            premise, conclusion = '', body.strip()

        # --- Arithmetic computation rules ---
        arith_premise = re.search(r'v3\s*=\s*v1\s*([+\-*/%])\s*v2', premise)
        if arith_premise:
            actual_op = arith_premise.group(1)
            arith_concl = re.search(r'\u3008v1\s*([+\-*/%])\s*v2', conclusion)
            if arith_concl:
                syntax_op = arith_concl.group(1)
                arith_map[syntax_op] = actual_op
                continue

        # --- Comparison true-rules ---
        if re.search(r'\u2192\s*true', conclusion):
            comp_concl = re.search(
                r'\u3008v1\s*(<=|>=|==|!=|<|>)\s*v2', conclusion
            )
            if comp_concl:
                syntax_op = comp_concl.group(1)
                if re.search(r'v1\s*<\s*v2', premise):
                    comp_map[syntax_op] = '<'
                elif re.search(r'v1\s*\u2264\s*v2', premise):
                    comp_map[syntax_op] = '<='
                elif re.search(r'v1\s*>\s*v2', premise):
                    comp_map[syntax_op] = '>'
                elif re.search(r'v1\s*\u2265\s*v2', premise):
                    comp_map[syntax_op] = '>='
                elif re.search(r'v1\s*=\s*v2', premise):
                    comp_map[syntax_op] = '=='
                elif re.search(r'v1\s*\u2260\s*v2', premise):
                    comp_map[syntax_op] = '!='
                continue

            logic_concl = re.search(
                r'\u3008q1\s*(&&|\|\|)\s*q2', conclusion
            )
            if logic_concl:
                syntax_op = logic_concl.group(1)
                if '\u22c0' in premise:
                    logic_map[syntax_op] = '&&'
                elif '\u22c1' in premise:
                    logic_map[syntax_op] = '||'
                continue

        # --- Unary operator rules ---
        if re.search(r'v2\s*=\s*-v1', premise):
            unary_concl = re.search(r'\u3008([+\-])\s*v1', conclusion)
            if unary_concl:
                unary_map[unary_concl.group(1)] = 'negate'
                continue

        unary_id = re.search(
            r'\u3008([+\-])\s*v\s*,.*\u2192\s+v\s*$', conclusion
        )
        if unary_id:
            unary_map[unary_id.group(1)] = 'identity'
            continue

    return arith_map, comp_map, logic_map, unary_map


def main():
    arith_map, comp_map, logic_map, unary_map = parse_sos_rules(
        '/app/semantics.txt'
    )

    result = {
        "arithmetic": arith_map,
        "comparison": comp_map,
        "logical": logic_map,
        "unary": unary_map,
    }

    os.makedirs('/app/analysis', exist_ok=True)
    with open('/app/analysis/mutations.json', 'w') as f:
        json.dump(result, f, indent=2, sort_keys=True)

    print("Mutation analysis written to /app/analysis/mutations.json")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
