#!/usr/bin/env python3
"""Generate conformance report from raw test results.

Reads raw_results.json and produces results.json with summary statistics.
"""
import json
import sys


def generate_report(raw_path, output_path):
    with open(raw_path) as f:
        raw = json.load(f)

    categories = {}
    total_tests = 0
    discrepancies = []

    for cat_name, cat_data in raw.items():
        tests = cat_data['tests']
        count = len(tests)
        total_tests += count

        pass_counts = {
            'pass_O0': 0, 'pass_O1': 0, 'pass_O2': 0, 'pass_O3': 0
        }

        for test in tests:
            for opt in ['-O0', '-O1', '-O2', '-O3']:
                level_data = test['levels'].get(opt, {})
                key = f'pass_{opt[1:]}'
                if (level_data.get('compiled', False)
                        and level_data.get('exit_code', 1) == 0):
                    pass_counts[key] += 1
                elif (level_data.get('compiled', False)
                      and level_data.get('exit_code', 0) != 0):
                    discrepancies.append({
                        'file': test['name'],
                        'category': cat_name,
                        'opt_level': opt,
                        'exit_code': level_data['exit_code']
                    })

        categories[cat_name] = {
            'count': count,
            **pass_counts,
            'pass_rate_O0': pass_counts['pass_O0'] / count,
            'pass_rate_O3': pass_counts['pass_O3'] / count,
        }

    report = {
        'total_tests': total_tests,
        'categories': categories,
        'discrepancies': discrepancies,
        'compilers_tested': ['gcc'],
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")
    print(f"Total tests: {total_tests}")
    overall_pass = sum(
        c['pass_rate_O0'] for c in categories.values()
    ) / len(categories)
    print(f"Overall O0 pass rate: {overall_pass:.1%}")


if __name__ == '__main__':
    raw_path = sys.argv[1] if len(sys.argv) > 1 else '/app/raw_results.json'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/results.json'
    generate_report(raw_path, output_path)
