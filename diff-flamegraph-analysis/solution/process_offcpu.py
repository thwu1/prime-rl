#!/usr/bin/env python3
"""Convert bpftrace @usecs map format off-CPU stacks to folded format.

Input format (leaf-first):
    @usecs[
        finish_task_switch
        schedule
        ...
        main
    ]: 5200

Output (root-first folded):
    main;...;schedule;finish_task_switch 5200
"""

import re


def parse_bpftrace_usecs(path):
    """Parse bpftrace @usecs[...]: N blocks."""
    with open(path) as f:
        content = f.read()

    pattern = r'@usecs\[\s*(.*?)\s*\]:\s*(\d+)'
    matches = re.findall(pattern, content, re.DOTALL)

    folded = []
    for stack_text, count_str in matches:
        frames = [line.strip() for line in stack_text.strip().split('\n')
                  if line.strip()]
        # Reverse: bpftrace prints leaf-first, folded format is root-first
        frames.reverse()
        folded.append(';'.join(frames) + ' ' + count_str)

    return folded


def main():
    folded_lines = parse_bpftrace_usecs('/app/traces/offcpu_stacks.txt')
    with open('/app/output/offcpu.folded', 'w') as f:
        f.write('\n'.join(folded_lines) + '\n')
    print(f"Wrote {len(folded_lines)} off-CPU stacks to /app/output/offcpu.folded")


if __name__ == '__main__':
    main()
