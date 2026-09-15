"""
Writes the four register allocator and codegen implementations to /app/.
"""
import textwrap

LIVENESS_CODE = textwrap.dedent(r'''
"""
Liveness analysis via backward dataflow with worklist algorithm.
"""
from typing import Dict, List, Set
from cfg import CFG, BasicBlock, Instruction, Location, reads_of, writes_of, Jump, JumpIf


def analyze_liveness(cfg: CFG) -> Dict[str, List[Set[Location]]]:
    """
    Perform backward dataflow liveness analysis on the given CFG.
    Returns dict mapping block label -> list of live-after sets (one per instruction).
    """
    # Build predecessor map (for backward analysis, we need successors)
    successor_map: Dict[str, List[str]] = {}
    for label, block in cfg.blocks.items():
        successor_map[label] = block.successors()

    # Initialize live-in sets for each block to empty
    live_in: Dict[str, Set[Location]] = {label: set() for label in cfg.blocks}
    live_after_result: Dict[str, List[Set[Location]]] = {}

    # Worklist algorithm: iterate until fixed point
    worklist = list(cfg.blocks.keys())
    changed = True
    while changed:
        changed = False
        for label in list(worklist):
            block = cfg.blocks[label]
            instrs = block.instrs

            # Compute live-out for this block = union of live-in of all successors
            succs = successor_map[label]
            live_out: Set[Location] = set()
            for s in succs:
                if s in live_in:
                    live_out |= live_in[s]

            # Compute live-after sets backward through the block
            n = len(instrs)
            la_sets: List[Set[Location]] = [set() for _ in range(n)]

            # Live-after of last instruction = live_out
            la_sets[n - 1] = set(live_out)

            # Compute live-before of last instruction
            current_live = set(live_out)

            # Walk backward
            for k in range(n - 1, -1, -1):
                instr = instrs[k]
                if k < n - 1:
                    la_sets[k] = set(current_live)
                else:
                    la_sets[k] = set(live_out)

                # L_before(k) = (L_after(k) - writes(k)) | reads(k)
                w = writes_of(instr)
                r = reads_of(instr)
                current_live = (la_sets[k] - w) | r

            # current_live is now live-in for this block
            new_live_in = current_live
            if new_live_in != live_in[label]:
                live_in[label] = new_live_in
                changed = True

            live_after_result[label] = la_sets

    return live_after_result
''')

INTERFERENCE_CODE = textwrap.dedent(r'''
"""
Interference graph and move graph construction from liveness information.
"""
from typing import Dict, List, Set, Tuple
from cfg import (CFG, BasicBlock, Instruction, Instr, Callq, Jump, JumpIf,
                 Location, Var, Reg, Immediate, Deref,
                 reads_of, writes_of, CALLER_SAVE_REGS, RESERVED_REGS)

Graph = Dict[Location, Set[Location]]


def _add_edge(graph: Graph, u: Location, v: Location):
    """Add an undirected edge u-v to the graph."""
    if u == v:
        return
    if u not in graph:
        graph[u] = set()
    if v not in graph:
        graph[v] = set()
    graph[u].add(v)
    graph[v].add(u)


def _is_reserved(loc: Location) -> bool:
    return isinstance(loc, Reg) and loc.name in RESERVED_REGS


def _is_move(instr: Instruction) -> bool:
    """Check if instruction is a register-register or var-var move."""
    if isinstance(instr, Instr) and instr.op == 'movq':
        src, dst = instr.args[0], instr.args[1]
        return isinstance(src, (Var, Reg)) and isinstance(dst, (Var, Reg))
    return False


def build_interference(cfg: CFG,
                       live_after_sets: Dict[str, List[Set[Location]]]
                       ) -> Tuple[Graph, Graph]:
    interfere: Graph = {}
    moves: Graph = {}

    # Ensure all variables/regs that appear anywhere are vertices
    for block in cfg.blocks.values():
        for instr in block.instrs:
            for loc in reads_of(instr) | writes_of(instr):
                if not _is_reserved(loc):
                    if loc not in interfere:
                        interfere[loc] = set()
                    if loc not in moves:
                        moves[loc] = set()

    for label, block in cfg.blocks.items():
        la_list = live_after_sets[label]
        for k, instr in enumerate(block.instrs):
            live_after = la_list[k]

            if isinstance(instr, Instr):
                if _is_move(instr):
                    # Rule 3: move instruction
                    src_set = reads_of(instr)
                    dst_set = writes_of(instr)
                    for d in dst_set:
                        if _is_reserved(d):
                            continue
                        for v in live_after:
                            if _is_reserved(v):
                                continue
                            if v != d and v not in src_set:
                                _add_edge(interfere, d, v)
                    # Add to move graph
                    src_locs = [a for a in [instr.args[0]] if isinstance(a, (Var, Reg)) and not _is_reserved(a)]
                    dst_locs = [a for a in [instr.args[1]] if isinstance(a, (Var, Reg)) and not _is_reserved(a)]
                    for s in src_locs:
                        for d in dst_locs:
                            if s != d:
                                _add_edge(moves, s, d)
                else:
                    # Rule 1: arithmetic instruction
                    dst_set = writes_of(instr)
                    for d in dst_set:
                        if _is_reserved(d):
                            continue
                        for v in live_after:
                            if _is_reserved(v):
                                continue
                            if v != d:
                                _add_edge(interfere, d, v)

            elif isinstance(instr, Callq):
                # Rule 2: call instruction
                for rname in CALLER_SAVE_REGS:
                    r = Reg(rname)
                    if _is_reserved(r):
                        continue
                    for v in live_after:
                        if _is_reserved(v):
                            continue
                        if v != r:
                            _add_edge(interfere, r, v)

    return interfere, moves
''')

COLORING_CODE = textwrap.dedent(r'''
"""
DSATUR graph coloring with move biasing for register allocation.
"""
from typing import Dict, Set, Optional
from cfg import Location, Var, Reg

Graph = Dict[Location, Set[Location]]


def dsatur_color(vertices: Set[Location],
                 interfere: Graph,
                 moves: Graph,
                 precolored: Dict[Location, int]) -> Dict[Location, int]:
    """
    Color the vertices using DSATUR with move biasing.
    """
    coloring: Dict[Location, int] = {}
    saturation: Dict[Location, Set[int]] = {v: set() for v in vertices}

    # Assign pre-colored vertices and update saturation
    for loc, color in precolored.items():
        coloring[loc] = color
        # Update neighbors' saturation
        for neighbor in interfere.get(loc, set()):
            if neighbor in saturation:
                saturation[neighbor].add(color)

    uncolored = set(vertices) - set(precolored.keys())

    while uncolored:
        # Pick vertex with maximum saturation
        # Break ties by: (1) highest interference degree, (2) move-bias preference
        best = None
        best_sat = -1
        best_degree = -1
        best_has_move_color = False

        for v in uncolored:
            sat = len(saturation[v])
            degree = len(interfere.get(v, set()))
            # Check if any move-related neighbor is colored with an available color
            has_move_color = False
            for m in moves.get(v, set()):
                if m in coloring and coloring[m] not in saturation[v]:
                    has_move_color = True
                    break

            if (sat > best_sat or
                (sat == best_sat and degree > best_degree) or
                (sat == best_sat and degree == best_degree and has_move_color and not best_has_move_color)):
                best = v
                best_sat = sat
                best_degree = degree
                best_has_move_color = has_move_color

        v = best

        # Choose color: prefer move-biased color if available
        forbidden = saturation[v]

        # Check move-related neighbors for biased colors
        biased_colors = []
        for m in moves.get(v, set()):
            if m in coloring:
                c = coloring[m]
                if c not in forbidden:
                    biased_colors.append(c)

        if biased_colors:
            color = min(biased_colors)
        else:
            # Find lowest available color
            color = 0
            while color in forbidden:
                color += 1

        coloring[v] = color
        uncolored.remove(v)

        # Update saturation of neighbors
        for neighbor in interfere.get(v, set()):
            if neighbor in saturation:
                saturation[neighbor].add(color)

    return coloring
''')

CODEGEN_CODE = textwrap.dedent(r'''
"""
x86-64 code generation from an allocated control flow graph.
Emits AT&T syntax assembly for a function named 'program' following
the System V AMD64 ABI.
"""
from typing import Dict
from cfg import (CFG, Instr, Callq, Jump, JumpIf,
                 Var, Reg, Immediate, Deref,
                 CALLEE_SAVE_REGS)


def emit_x86(cfg: CFG, allocation: Dict[str, object]) -> str:
    """
    Generate x86-64 assembly (AT&T syntax) for the allocated program.
    """
    lines = []

    # Determine which callee-save registers are used in the allocation
    used_callee = []
    for reg_name in CALLEE_SAVE_REGS:
        for var_name, loc in allocation.items():
            if isinstance(loc, Reg) and loc.name == reg_name:
                used_callee.append(reg_name)
                break

    # Determine stack space needed for spills
    spill_space = 0
    for loc in allocation.values():
        if isinstance(loc, Deref):
            spill_space = max(spill_space, abs(loc.offset))

    # Callee-save offsets: stored below the spill area in the frame
    callee_offsets = {}
    for i, rname in enumerate(used_callee):
        callee_offsets[rname] = -(spill_space + 8 * (i + 1))

    callee_save_space = 8 * len(used_callee)

    # Total frame size (must be multiple of 16 for stack alignment)
    frame_size = spill_space + callee_save_space
    if frame_size > 0 and frame_size % 16 != 0:
        frame_size += 16 - (frame_size % 16)

    # --- Prologue ---
    lines.append('.globl program')
    lines.append('.type program, @function')
    lines.append('program:')
    lines.append('    pushq %rbp')
    lines.append('    movq %rsp, %rbp')
    if frame_size > 0:
        lines.append(f'    subq ${frame_size}, %rsp')

    # Save callee-save registers
    for rname in used_callee:
        off = callee_offsets[rname]
        lines.append(f'    movq %{rname}, {off}(%rbp)')

    # --- Helper functions ---
    def fmt(arg):
        """Format an instruction argument as AT&T syntax operand."""
        if isinstance(arg, Var):
            loc = allocation[arg.name]
            if isinstance(loc, Reg):
                return f'%{loc.name}'
            elif isinstance(loc, Deref):
                return f'{loc.offset}(%{loc.reg})'
        elif isinstance(arg, Reg):
            return f'%{arg.name}'
        elif isinstance(arg, Immediate):
            return f'${arg.value}'
        elif isinstance(arg, Deref):
            return f'{arg.offset}(%{arg.reg})'
        raise ValueError(f'Unknown arg: {arg}')

    def is_mem(arg):
        """Check if an argument resolves to a memory operand."""
        if isinstance(arg, Var):
            return isinstance(allocation.get(arg.name), Deref)
        return isinstance(arg, Deref)

    # --- Emit basic blocks ---
    entry = cfg.entry
    other_labels = sorted([l for l in cfg.blocks if l != entry and l != 'conclusion'])
    block_order = [entry] + other_labels

    for label in block_order:
        block = cfg.blocks[label]
        lines.append(f'.L_{label}:')
        for instr in block.instrs:
            if isinstance(instr, Instr):
                if len(instr.args) == 2:
                    src, dst = instr.args
                    if is_mem(src) and is_mem(dst):
                        # x86 forbids two memory operands; use %rax as scratch
                        lines.append(f'    movq {fmt(src)}, %rax')
                        lines.append(f'    {instr.op} %rax, {fmt(dst)}')
                    else:
                        lines.append(f'    {instr.op} {fmt(src)}, {fmt(dst)}')
                elif len(instr.args) == 1:
                    lines.append(f'    {instr.op} {fmt(instr.args[0])}')
                else:
                    lines.append(f'    {instr.op}')
            elif isinstance(instr, Callq):
                lines.append(f'    callq {instr.label}')
            elif isinstance(instr, Jump):
                lines.append(f'    jmp .L_{instr.label}')
            elif isinstance(instr, JumpIf):
                lines.append(f'    j{instr.cc} .L_{instr.label}')

    # --- Epilogue (conclusion label) ---
    lines.append('.L_conclusion:')
    for rname in used_callee:
        off = callee_offsets[rname]
        lines.append(f'    movq {off}(%rbp), %{rname}')
    lines.append('    leave')
    lines.append('    retq')

    return '\n'.join(lines) + '\n'
''')


def main():
    with open('/app/liveness.py', 'w') as f:
        f.write(LIVENESS_CODE.lstrip('\n'))

    with open('/app/interference.py', 'w') as f:
        f.write(INTERFERENCE_CODE.lstrip('\n'))

    with open('/app/coloring.py', 'w') as f:
        f.write(COLORING_CODE.lstrip('\n'))

    with open('/app/codegen.py', 'w') as f:
        f.write(CODEGEN_CODE.lstrip('\n'))

    print("Wrote liveness.py, interference.py, coloring.py, codegen.py to /app/")


if __name__ == '__main__':
    main()
