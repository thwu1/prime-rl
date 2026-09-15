#!/usr/bin/env python3
"""Execute all IMP programs under both mutated and standard semantics.
Produce divergence analysis and generate verification program."""

import json
import os
import sys

from imp_parser import parse
from interpreter import Interpreter
from analyze import parse_sos_rules
from imp_lexer import lexer as base_lexer, tokens as _tok  # noqa: F401

# Standard IMP semantics: every operator does what its token means.
STANDARD_ARITH = {'+': '+', '-': '-', '*': '*', '/': '/', '%': '%'}
STANDARD_COMP = {
    '<': '<', '<=': '<=', '>': '>', '>=': '>=',
    '==': '==', '!=': '!=',
}
STANDARD_LOGIC = {'&&': '&&', '||': '||'}
STANDARD_UNARY = {'+': 'identity', '-': 'negate'}

# Maps token types to mutation categories and standard operator strings.
TOKEN_TO_CATEGORY = {
    'PLUS': ('arithmetic', '+'),
    'MINUS': ('arithmetic', '-'),
    'TIMES': ('arithmetic', '*'),
    'DIVIDE': ('arithmetic', '/'),
    'MOD': ('arithmetic', '%'),
    'LT': ('comparison', '<'),
    'LEQ': ('comparison', '<='),
    'GT': ('comparison', '>'),
    'GEQ': ('comparison', '>='),
    'EQ': ('comparison', '=='),
    'NEQ': ('comparison', '!='),
    'AND': ('logical', '&&'),
    'OR': ('logical', '||'),
}


def get_operators_used(source):
    """Return set of (category, operator_string) pairs used in program."""
    lex = base_lexer.clone()
    lex.input(source)
    ops = set()
    for tok in lex:
        if tok.type in TOKEN_TO_CATEGORY:
            ops.add(TOKEN_TO_CATEGORY[tok.type])
    return ops


def get_affected_categories(source, arith_map, comp_map, logic_map):
    """Determine which mutation categories have mutated operators in source."""
    ops = get_operators_used(source)
    categories = set()
    all_maps = {
        'arithmetic': (arith_map, STANDARD_ARITH),
        'comparison': (comp_map, STANDARD_COMP),
        'logical': (logic_map, STANDARD_LOGIC),
    }
    for cat, op_str in ops:
        if cat in all_maps:
            mut_map, std_map = all_maps[cat]
            if mut_map.get(op_str) != std_map.get(op_str):
                categories.add(cat)
    return sorted(categories)


def generate_verification_program():
    """Create a program where check=1 under mutated semantics, check=0 under standard.

    Under mutated: (5 - 3) → 5+3=8 (syntax - computes +),
                   (8 < 1) → 8>1=true (syntax < checks >), take then branch.
    Under standard: (5-3)=2, (2<1)=false, take else branch.
    """
    return (
        "int check;\n"
        "check = 0;\n"
        "if(((5 - 3) < 1))\n"
        "{\n"
        "    check = 1;\n"
        "}\n"
        "else\n"
        "{\n"
        "    check = 0;\n"
        "};\n"
    )


def run_programs(programs_dir, arith_map, comp_map, logic_map, unary_map):
    """Execute all .imp programs and return {basename: final_state}."""
    results = {}
    for fname in sorted(os.listdir(programs_dir)):
        if not fname.endswith('.imp'):
            continue
        with open(os.path.join(programs_dir, fname)) as f:
            source = f.read()
        ast = parse(source)
        interp = Interpreter(arith_map, comp_map, logic_map, unary_map)
        results[fname.replace('.imp', '')] = interp.run(ast)
    return results


def save_results(results, output_dir):
    """Write each program's result to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    for basename, state in results.items():
        with open(os.path.join(output_dir, f'{basename}.json'), 'w') as f:
            json.dump(state, f, sort_keys=True)


def run_mutated(programs_dir, arith_map, comp_map, logic_map, unary_map):
    """Execute all programs under mutated semantics."""
    results = run_programs(
        programs_dir, arith_map, comp_map, logic_map, unary_map,
    )
    save_results(results, '/app/results')
    print('Mutated results:')
    for name, state in sorted(results.items()):
        print(f'  {name}: {state}')
    return results


def run_standard(programs_dir):
    """Execute all programs under standard semantics."""
    results = run_programs(
        programs_dir,
        STANDARD_ARITH, STANDARD_COMP, STANDARD_LOGIC, STANDARD_UNARY,
    )
    save_results(results, '/app/results_standard')
    print('Standard results:')
    for name, state in sorted(results.items()):
        print(f'  {name}: {state}')
    return results


def compute_divergence(mutated, standard, programs_dir, arith_map, comp_map,
                       logic_map):
    """Produce divergence analysis comparing mutated vs standard results."""
    divergence = {}
    for basename in sorted(set(mutated) | set(standard)):
        mut_state = mutated.get(basename, {})
        std_state = standard.get(basename, {})
        differs = mut_state != std_state

        # Read source to find which operators are used.
        src_path = os.path.join(programs_dir, f'{basename}.imp')
        if os.path.isfile(src_path):
            with open(src_path) as f:
                source = f.read()
            affected = get_affected_categories(
                source, arith_map, comp_map, logic_map,
            ) if differs else []
        else:
            affected = []

        divergence[basename] = {
            'mutated_state': mut_state,
            'standard_state': std_state,
            'differs': differs,
            'affected_categories': affected,
        }

    os.makedirs('/app/analysis', exist_ok=True)
    with open('/app/analysis/divergence.json', 'w') as f:
        json.dump(divergence, f, indent=2, sort_keys=True)

    print('\nDivergence analysis:')
    for name, entry in sorted(divergence.items()):
        status = 'DIFFERS' if entry['differs'] else 'SAME'
        cats = ', '.join(entry['affected_categories']) or 'none'
        print(f'  {name}: {status} (affected: {cats})')

    return divergence


def main():
    programs_dir = '/app/programs'

    arith_map, comp_map, logic_map, unary_map = parse_sos_rules(
        '/app/semantics.txt',
    )
    print('Extracted mutations from SOS rules:')
    print(f'  Arithmetic: {arith_map}')
    print(f'  Comparison: {comp_map}')
    print(f'  Logical:    {logic_map}')
    print(f'  Unary:      {unary_map}')
    print()

    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    # Generate verification program (always, before running).
    verify_path = os.path.join(programs_dir, 'verification.imp')
    if not os.path.isfile(verify_path):
        with open(verify_path, 'w') as f:
            f.write(generate_verification_program())
        print('Generated verification.imp')

    if mode in ('mutated', 'all'):
        mutated = run_mutated(
            programs_dir, arith_map, comp_map, logic_map, unary_map,
        )
    if mode in ('standard', 'all'):
        standard = run_standard(programs_dir)
    if mode in ('diverge', 'all'):
        if mode == 'diverge':
            # Load from saved results.
            mutated = {}
            standard = {}
            for fname in os.listdir('/app/results'):
                if fname.endswith('.json'):
                    bn = fname.replace('.json', '')
                    with open(f'/app/results/{fname}') as f:
                        mutated[bn] = json.load(f)
            for fname in os.listdir('/app/results_standard'):
                if fname.endswith('.json'):
                    bn = fname.replace('.json', '')
                    with open(f'/app/results_standard/{fname}') as f:
                        standard[bn] = json.load(f)
        compute_divergence(
            mutated, standard, programs_dir,
            arith_map, comp_map, logic_map,
        )


if __name__ == '__main__':
    main()
