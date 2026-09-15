#!/usr/bin/env python3
"""Generate a Graphviz DOT diagram of the MOESI protocol state transitions.

Reads protocol transition definitions and outputs DOT format to stdout.
Pipe through 'dot -Tsvg' to render as SVG.
"""


CACHE_STATES = ["Modified", "Owned", "Exclusive", "Shared", "Invalid"]

# (from_state, to_state, label)
CACHE_TRANSITIONS = [
    # GetS responses (cache receives data from directory)
    ("Invalid", "Exclusive", "GetS\\n(uncached)"),
    ("Invalid", "Shared", "GetS\\n(shared/EM)"),
    # GetM responses (cache receives exclusive ownership)
    ("Invalid", "Modified", "GetM"),
    ("Shared", "Modified", "GetM"),
    ("Owned", "Modified", "GetM"),
    # Silent upgrades (no directory interaction)
    ("Exclusive", "Modified", "store\\n(silent)"),
    # Invalidation (Inv / FwdGetM from directory)
    ("Shared", "Invalid", "Inv"),
    ("Modified", "Invalid", "FwdGetM"),
    ("Owned", "Invalid", "FwdGetM"),
    ("Exclusive", "Invalid", "Inv"),
    # Forwarding (FwdGetS from directory)
    ("Modified", "Owned", "FwdGetS"),
    ("Exclusive", "Shared", "FwdGetS"),
    # Writebacks / evictions
    ("Modified", "Invalid", "PutM"),
    ("Owned", "Invalid", "PutO"),
    ("Shared", "Invalid", "PutS"),
    ("Exclusive", "Invalid", "PutS"),
]

DIR_STATES = ["Uncached", "Shared", "ExclMod"]

DIR_TRANSITIONS = [
    ("Uncached", "ExclMod", "GetS\\n(first)"),
    ("Uncached", "ExclMod", "GetM"),
    ("Shared", "Shared", "GetS"),
    ("Shared", "ExclMod", "GetM"),
    ("ExclMod", "Shared", "GetS\\n(fwd)"),
    ("ExclMod", "ExclMod", "GetM\\n(fwd)"),
    ("ExclMod", "Uncached", "PutM"),
    ("Shared", "Uncached", "PutS\\n(last)"),
]


def generate_dot():
    lines = [
        'digraph MOESI {',
        '    rankdir=LR;',
        '    compound=true;',
        '    fontname="Helvetica";',
        '    node [fontname="Helvetica", fontsize=10];',
        '    edge [fontname="Helvetica", fontsize=8];',
        '',
        '    subgraph cluster_cache {',
        '        label="Cache States";',
        '        style=dashed;',
        '        color=blue;',
    ]
    for s in CACHE_STATES:
        shape = "doublecircle" if s == "Invalid" else "circle"
        lines.append(f'        C_{s} [label="{s}", shape={shape}];')
    lines.append('    }')
    lines.append('')

    for fr, to, label in CACHE_TRANSITIONS:
        lines.append(f'    C_{fr} -> C_{to} [label="{label}"];')

    lines.append('')
    lines.append('    subgraph cluster_directory {')
    lines.append('        label="Directory States";')
    lines.append('        style=dashed;')
    lines.append('        color=red;')
    for s in DIR_STATES:
        shape = "doublecircle" if s == "Uncached" else "circle"
        lines.append(f'        D_{s} [label="{s}", shape={shape}];')
    lines.append('    }')
    lines.append('')

    for fr, to, label in DIR_TRANSITIONS:
        lines.append(f'    D_{fr} -> D_{to} [label="{label}"];')

    lines.append('}')
    return '\n'.join(lines)


if __name__ == '__main__':
    print(generate_dot())
