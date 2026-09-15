
"""Graphviz DOT output for CFG visualization — solution."""

import sys
sys.path.insert(0, "/app")

from tac_parser import Function, emit_instruction
from cfg import build_cfg


def cfg_to_dot(func: Function) -> str:
    """Generate a Graphviz DOT string for the CFG of the given function."""
    cfg = build_cfg(func.body)
    reachable = cfg.reachable_block_ids()

    lines = [f'digraph "{func.name}" {{']
    lines.append('  rankdir=TB;')
    lines.append('  node [shape=box, fontname="Courier", fontsize=10];')

    for bid in sorted(cfg.blocks.keys()):
        if bid not in reachable:
            continue
        block = cfg.blocks[bid]
        label_parts = []
        for instr in block.instructions:
            text = emit_instruction(instr).strip()
            text = text.replace('\\', '\\\\').replace('"', '\\"')
            label_parts.append(text)
        label = '\\l'.join(label_parts) + '\\l'

        style = ', style=bold' if bid == cfg.entry_id else ''
        lines.append(f'  B{bid} [label="{label}"{style}];')

    for bid in sorted(cfg.blocks.keys()):
        if bid not in reachable:
            continue
        block = cfg.blocks[bid]
        for succ in block.successors:
            if succ in reachable:
                lines.append(f'  B{bid} -> B{succ};')

    lines.append('}')
    return '\n'.join(lines) + '\n'
