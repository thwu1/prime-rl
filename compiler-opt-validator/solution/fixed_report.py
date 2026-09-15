#!/usr/bin/env python3
"""Generate conformance report from raw test results — FIXED.

Handles dual-compiler format and avoids division-by-zero.
"""
import json
import sys


def generate_report(raw_path, output_path):
    with open(raw_path) as f:
        raw = json.load(f)

    compilers_tested = list(raw.keys())
    categories = {}
    total_tests = 0
    discrepancies = []

    first_compiler = compilers_tested[0]
    for cat_name, cat_data in raw[first_compiler].items():
        tests = cat_data['tests']
        count = len(tests)
        total_tests += count

        cat_result = {'count': count}

        for compiler_name in compilers_tested:
            comp_cat = raw[compiler_name].get(cat_name, {'tests': []})
            comp_tests = comp_cat['tests']

            pass_counts = {}
            for opt in ['-O0', '-O1', '-O2', '-O3']:
                key = f'pass_{opt[1:]}'
                passed = 0
                for test in comp_tests:
                    level_data = test['levels'].get(opt, {})
                    if (level_data.get('compiled', False)
                            and level_data.get('exit_code', 1) == 0):
                        passed += 1
                    elif (level_data.get('compiled', False)
                          and level_data.get('exit_code', 0) != 0):
                        discrepancies.append({
                            'file': test['name'],
                            'category': cat_name,
                            'compiler': compiler_name,
                            'opt_level': opt,
                            'exit_code': level_data['exit_code']
                        })
                pass_counts[key] = passed

            cat_result[compiler_name] = pass_counts

        categories[cat_name] = cat_result

    report = {
        'total_tests': total_tests,
        'categories': categories,
        'discrepancies': discrepancies,
        'compilers_tested': compilers_tested,
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")
    print(f"Total tests: {total_tests}")
    print(f"Compilers tested: {compilers_tested}")


if __name__ == '__main__':
    raw_path = sys.argv[1] if len(sys.argv) > 1 else '/app/raw_results.json'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/results.json'
    generate_report(raw_path, output_path)
