#!/usr/bin/env python3
"""Generate Graphviz DOT control flow graph from TAC source."""
import sys
import re


def classify(line):
    """Classify an instruction line by type."""
    line = line.strip()
    if line.startswith('LABEL '):
        return 'LABEL', line[6:].strip()
    if line.startswith('GOTO '):
        return 'GOTO', line[5:].strip()
    m = re.match(r'IF\s+\S+\s+(?:==|!=|<=|>=|<|>)\s+\S+\s+GOTO\s+(\S+)', line)
    if m:
        return 'IF', m.group(1)
    return 'OTHER', None


def sanitize_id(name):
    """Make a string safe for use as a DOT node ID."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', name)


def main():
    if len(sys.argv) < 2:
        print("Usage: cfg_gen.py <program.tac> [title]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    title = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]

    lines = [l.strip() for l in text.strip().split('\n')
             if l.strip() and not l.strip().startswith('#')]

    if not lines:
        print(f'digraph "{title}" {{}}')
        return

    # Identify block start indices
    starts = {0}
    label_map = {}
    for i, line in enumerate(lines):
        kind, arg = classify(line)
        if kind == 'LABEL':
            starts.add(i)
            label_map[arg] = i
        elif kind in ('GOTO', 'IF'):
            if i + 1 < len(lines):
                starts.add(i + 1)

    sorted_starts = sorted(starts)

    # Build basic blocks
    blocks = []
    for idx, s in enumerate(sorted_starts):
        e = sorted_starts[idx + 1] if idx + 1 < len(sorted_starts) else len(lines)
        blines = lines[s:e]
        kind, arg = classify(blines[0])
        name = arg if kind == 'LABEL' else f'B{s}'
        blocks.append((name, blines, s))

    # Map label names to block names
    label_to_block = {}
    for name, blines, _ in blocks:
        kind, arg = classify(blines[0])
        if kind == 'LABEL':
            label_to_block[arg] = name

    # Build edges
    edges = []
    for i, (name, blines, _) in enumerate(blocks):
        last_kind, last_arg = classify(blines[-1])
        if last_kind == 'GOTO':
            if last_arg in label_to_block:
                edges.append((name, label_to_block[last_arg]))
        elif last_kind == 'IF':
            if last_arg in label_to_block:
                edges.append((name, label_to_block[last_arg]))
            if i + 1 < len(blocks):
                edges.append((name, blocks[i + 1][0]))
        else:
            if i + 1 < len(blocks):
                edges.append((name, blocks[i + 1][0]))

    # Generate DOT output
    out = [f'digraph "{title}" {{']
    out.append('    node [shape=box fontname="Courier" fontsize=10];')
    out.append('    rankdir=TB;')

    for name, blines, _ in blocks:
        nid = sanitize_id(name)
        escaped = []
        for bl in blines:
            escaped.append(bl.replace('\\', '\\\\').replace('"', '\\"'))
        content = '\\l'.join(escaped) + '\\l'
        out.append(f'    {nid} [label="{name}:\\n{content}"];')

    for src, dst in edges:
        out.append(f'    {sanitize_id(src)} -> {sanitize_id(dst)};')

    out.append('}')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
