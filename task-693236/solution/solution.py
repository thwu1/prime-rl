
"""Reference implementation of the x86-64 register allocator."""

import sys
sys.path.insert(0, '/app')
sys.path.insert(1, '/opt/task_lib')

from ir import (
    X86Program, Instr, Callq, Jump, JumpIf,
    Immediate, Reg, Var, Deref,
    reads, writes, is_move, variables_in_program,
    block_successors,
    CALLER_SAVED, CALLEE_SAVED, ALLOCATABLE, ARG_REGISTERS,
)
from graph import UndirectedAdjList
from priority_queue import PriorityQueue


def uncover_live(program):
    """Backward dataflow liveness analysis with fixed-point iteration."""
    blocks = program.blocks

    # Fixed-point: track live-before set for each block's first instruction
    live_before_block = {label: set() for label in blocks}

    changed = True
    while changed:
        changed = False
        for label in blocks:
            instrs = blocks[label]
            succs = block_successors(instrs)

            # Live after entire block = union of live-before of successor blocks
            live = set()
            for s in succs:
                if s == 'conclusion':
                    live.add(Reg('rax'))
                elif s in live_before_block:
                    live |= live_before_block[s]

            # Walk instructions bottom-to-top
            for instr in reversed(instrs):
                w = writes(instr)
                r = reads(instr)
                live = (live - w) | r

            if live != live_before_block[label]:
                live_before_block[label] = live
                changed = True

    # Second pass: compute per-instruction live-after sets
    result = {}
    for label in blocks:
        instrs = blocks[label]
        succs = block_successors(instrs)

        live = set()
        for s in succs:
            if s == 'conclusion':
                live.add(Reg('rax'))
            elif s in live_before_block:
                live |= live_before_block[s]

        live_afters = []
        for instr in reversed(instrs):
            live_afters.append(frozenset(live))
            w = writes(instr)
            r = reads(instr)
            live = (live - w) | r
        live_afters.reverse()
        result[label] = live_afters

    return result


def build_interference(program, live_after_sets):
    """Build interference graph using the three rules."""
    graph = UndirectedAdjList()

    # Ensure all variables and allocatable registers are vertices
    for var in variables_in_program(program):
        graph.add_vertex(var)
    for r in ALLOCATABLE:
        graph.add_vertex(Reg(r))

    def _add_edge(u, v):
        if u != v and not graph.has_edge(u, v):
            graph.add_vertex(u)
            graph.add_vertex(v)
            graph.add_edge(u, v)

    for label, instrs in program.blocks.items():
        la_list = live_after_sets[label]
        for idx, instr in enumerate(instrs):
            la = la_list[idx]
            w_set = writes(instr)

            if is_move(instr):
                # Rule 3: skip edge between dst and src
                src = instr.args[0]
                for d in w_set:
                    for v in la:
                        if v != d and v != src:
                            _add_edge(d, v)
            else:
                # Rules 1 & 2 (general + call)
                for d in w_set:
                    for v in la:
                        if v != d:
                            _add_edge(d, v)

    return graph


def build_move_graph(program):
    """Build undirected graph of move-related variable/register pairs."""
    graph = UndirectedAdjList()

    for var in variables_in_program(program):
        graph.add_vertex(var)
    for r in ALLOCATABLE:
        graph.add_vertex(Reg(r))

    for label, instrs in program.blocks.items():
        for instr in instrs:
            if is_move(instr):
                src, dst = instr.args[0], instr.args[1]
                if src != dst and not graph.has_edge(src, dst):
                    graph.add_vertex(src)
                    graph.add_vertex(dst)
                    graph.add_edge(src, dst)

    return graph


def color_graph(interference, move_graph, variables):
    """DSATUR graph coloring with move biasing."""
    num_allocatable = len(ALLOCATABLE)

    # Pre-assign colors to physical registers
    color = {}
    for i, r in enumerate(ALLOCATABLE):
        color[Reg(r)] = i

    # Initialize saturation for each variable
    saturation = {v: set() for v in variables}
    for var in variables:
        if var in interference.out:
            for neighbor in interference.adjacent(var):
                if neighbor in color:
                    saturation[var].add(color[neighbor])

    # Worklist
    worklist = set(variables)

    while worklist:
        # Pick vertex with highest saturation; break ties by move-related score
        best = None
        best_sat = -1
        best_move_score = -1

        for v in worklist:
            sat = len(saturation.get(v, set()))

            move_score = 0
            if v in move_graph.out:
                for neighbor in move_graph.adjacent(v):
                    if neighbor in color:
                        move_score += 1

            if (sat > best_sat
                    or (sat == best_sat and move_score > best_move_score)):
                best = v
                best_sat = sat
                best_move_score = move_score

        # Try to pick a color from a move-related already-colored neighbor
        chosen = None
        if best in move_graph.out:
            for neighbor in move_graph.adjacent(best):
                if neighbor in color:
                    c = color[neighbor]
                    if c not in saturation.get(best, set()):
                        chosen = c
                        break

        # Fall back to lowest available color
        if chosen is None:
            c = 0
            while c in saturation.get(best, set()):
                c += 1
            chosen = c

        color[best] = chosen
        worklist.remove(best)

        # Update saturation of neighbors in interference graph
        if best in interference.out:
            for neighbor in interference.adjacent(best):
                if neighbor in saturation:
                    saturation[neighbor].add(chosen)

    return color


def assign_homes(program, coloring):
    """Map colors to registers / stack slots, replacing all Var operands."""
    num_allocatable = len(ALLOCATABLE)

    def map_op(op):
        if isinstance(op, Var):
            c = coloring.get(op)
            if c is None:
                return op
            if c < num_allocatable:
                return Reg(ALLOCATABLE[c])
            else:
                offset = -8 * (c - num_allocatable + 1)
                return Deref('rbp', offset)
        return op

    new_blocks = {}
    for label, instrs in program.blocks.items():
        new_instrs = []
        for instr in instrs:
            if isinstance(instr, Instr):
                new_instrs.append(Instr(instr.name, [map_op(a) for a in instr.args]))
            else:
                new_instrs.append(instr)
        new_blocks[label] = new_instrs

    # Compute stack space
    vars_prog = variables_in_program(program)
    max_color = -1
    for v in vars_prog:
        c = coloring.get(v, 0)
        if c > max_color:
            max_color = c

    spills = max(0, max_color - num_allocatable + 1)
    stack_space = spills * 8
    if stack_space % 16 != 0:
        stack_space += 16 - (stack_space % 16)

    # Track used callee-saved registers
    used_callee = []
    for v in vars_prog:
        c = coloring.get(v, 0)
        if c < num_allocatable:
            reg = ALLOCATABLE[c]
            if reg in CALLEE_SAVED and reg not in used_callee:
                used_callee.append(reg)

    return X86Program(
        blocks=new_blocks,
        stack_space=stack_space,
        used_callee_saved=used_callee,
    )


def patch_instructions(program):
    """Remove trivial moves, fix two-memory-operand violations."""
    new_blocks = {}
    for label, instrs in program.blocks.items():
        new_instrs = []
        for instr in instrs:
            if isinstance(instr, Instr):
                if instr.name == 'movq' and len(instr.args) == 2:
                    src, dst = instr.args
                    # Remove trivial moves
                    if src == dst:
                        continue
                    # Fix two-memory-operand
                    if isinstance(src, Deref) and isinstance(dst, Deref):
                        new_instrs.append(Instr('movq', [src, Reg('rax')]))
                        new_instrs.append(Instr('movq', [Reg('rax'), dst]))
                        continue
                elif (instr.name in ('addq', 'subq', 'xorq', 'andq', 'cmpq')
                      and len(instr.args) == 2):
                    src, dst = instr.args
                    if isinstance(src, Deref) and isinstance(dst, Deref):
                        new_instrs.append(Instr('movq', [src, Reg('rax')]))
                        new_instrs.append(Instr(instr.name, [Reg('rax'), dst]))
                        continue
            new_instrs.append(instr)
        new_blocks[label] = new_instrs

    return X86Program(
        blocks=new_blocks,
        stack_space=program.stack_space,
        used_callee_saved=program.used_callee_saved,
    )


def allocate_registers(program):
    """Full register allocation pipeline."""
    la = uncover_live(program)
    interference = build_interference(program, la)
    move_g = build_move_graph(program)
    variables = variables_in_program(program)
    coloring = color_graph(interference, move_g, variables)
    allocated = assign_homes(program, coloring)
    patched = patch_instructions(allocated)
    return patched
