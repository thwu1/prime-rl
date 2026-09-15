#!/usr/bin/env python3
"""Generate optimization report as JSON."""
import subprocess
import json


PROGRAMS = ['propagation', 'loop_analysis', 'diamond_flow', 'tricky']


def count_instructions(text):
    """Count non-blank, non-comment instructions."""
    return sum(1 for line in text.strip().split('\n')
               if line.strip() and not line.strip().startswith('#'))


def main():
    report = []
    for prog in PROGRAMS:
        orig_path = f'/app/programs/{prog}.tac'
        opt_path = f'/app/optimized/{prog}.tac'

        with open(orig_path) as f:
            orig_count = count_instructions(f.read())
        with open(opt_path) as f:
            opt_count = count_instructions(f.read())

        reduction = round((1 - opt_count / orig_count) * 100, 1) if orig_count > 0 else 0.0

        orig_out = subprocess.run(
            ['python3', '/app/tac_interpreter.py', orig_path],
            capture_output=True, text=True
        ).stdout.strip()
        opt_out = subprocess.run(
            ['python3', '/app/tac_interpreter.py', opt_path],
            capture_output=True, text=True
        ).stdout.strip()

        report.append({
            'program': f'{prog}.tac',
            'original_instructions': orig_count,
            'optimized_instructions': opt_count,
            'reduction_pct': reduction,
            'semantic_match': orig_out == opt_out
        })

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
