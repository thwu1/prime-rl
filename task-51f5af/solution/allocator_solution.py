"""Complete register allocator implementation.


Implements:
  1. Backward dataflow liveness analysis with fixed-point iteration
  2. Interference graph construction (with movq non-interference rule)
  3. Move graph construction
  4. DSATUR graph coloring with move biasing
  5. Home assignment (color → Reg / Deref)
  6. Instruction patching (no mem-to-mem)
  7. Prelude / conclusion generation
"""

import copy
import sys

from x86_ast import (
    X86Program, Instr, Callq, Jump, JumpIf,
    Variable, Immediate, Reg, ByteReg, Deref,
)
from graph import UndirectedAdjList
from priority_queue import PriorityQueue

# ── Register configuration ────────────────────────────────────────────

ALLOCATABLE_REGS = [
    'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10',  # caller-saved 0-6
    'rbx', 'r12', 'r13', 'r14',                        # callee-saved 7-10
]
NUM_COLORS = len(ALLOCATABLE_REGS)  # 11

REG_COLOR = {r: i for i, r in enumerate(ALLOCATABLE_REGS)}
REG_COLOR.update({
    'rax': -1, 'rsp': -2, 'rbp': -3, 'r11': -4, 'r15': -5,
    'al': -1, 'cl': 0,
})
COLOR_TO_REG = {i: r for i, r in enumerate(ALLOCATABLE_REGS)}

CALLER_SAVED = frozenset({
    'rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11',
})
CALLEE_SAVED = frozenset({'rbx', 'r12', 'r13', 'r14'})


# ── Read / Write sets ─────────────────────────────────────────────────

def _loc(a):
    """Return *a* if it is a location (Variable/Reg/ByteReg), else None."""
    return a if isinstance(a, (Variable, Reg, ByteReg)) else None


def read_vars(node):
    """Locations read by *node*."""
    result = set()
    if isinstance(node, Instr):
        op, args = node.instr, node.args
        if op in ('movq', 'movzbq'):
            s = _loc(args[0])
            if s:
                result.add(s)
            if isinstance(args[0], Deref):
                result.add(Reg(args[0].reg))
            if isinstance(args[1], Deref):
                result.add(Reg(args[1].reg))
        elif op in ('addq', 'subq', 'xorq'):
            for a in args:
                l = _loc(a)
                if l:
                    result.add(l)
                if isinstance(a, Deref):
                    result.add(Reg(a.reg))
        elif op == 'negq':
            l = _loc(args[0])
            if l:
                result.add(l)
            if isinstance(args[0], Deref):
                result.add(Reg(args[0].reg))
        elif op == 'cmpq':
            for a in args:
                l = _loc(a)
                if l:
                    result.add(l)
                if isinstance(a, Deref):
                    result.add(Reg(a.reg))
        elif op in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
            pass  # implicit EFLAGS read
        elif op == 'pushq':
            l = _loc(args[0])
            if l:
                result.add(l)
            if isinstance(args[0], Deref):
                result.add(Reg(args[0].reg))
        elif op == 'popq':
            if isinstance(args[0], Deref):
                result.add(Reg(args[0].reg))
        elif op == 'retq':
            result.add(Reg('rax'))
    elif isinstance(node, Callq):
        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']
        for i in range(min(node.num_args, len(arg_regs))):
            result.add(Reg(arg_regs[i]))
    return result


def write_vars(node):
    """Locations written by *node*."""
    result = set()
    if isinstance(node, Instr):
        op, args = node.instr, node.args
        if op in ('movq', 'movzbq'):
            l = _loc(args[1])
            if l:
                result.add(l)
        elif op in ('addq', 'subq', 'xorq'):
            l = _loc(args[1])
            if l:
                result.add(l)
        elif op == 'negq':
            l = _loc(args[0])
            if l:
                result.add(l)
        elif op in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
            l = _loc(args[0])
            if l:
                result.add(l)
        elif op == 'popq':
            l = _loc(args[0])
            if l:
                result.add(l)
    elif isinstance(node, Callq):
        for r in CALLER_SAVED:
            result.add(Reg(r))
    return result


# ── Successors ─────────────────────────────────────────────────────────

def _block_successors(block):
    """Labels of successor blocks (excluding 'conclusion')."""
    succs = set()
    for node in block:
        if isinstance(node, Jump) and node.label != 'conclusion':
            succs.add(node.label)
        elif isinstance(node, JumpIf) and node.label != 'conclusion':
            succs.add(node.label)
    return succs


# ── 1. Liveness analysis ──────────────────────────────────────────────

def uncover_live(program):
    """Return ``{label: [live_after_set_per_instr]}`` via fixed-point iteration."""
    blocks = program.body

    # live_before[label] = set of locations live at block entry
    live_before = {label: set() for label in blocks}

    # Fixed-point
    changed = True
    while changed:
        changed = False
        for label, instrs in blocks.items():
            succs = _block_successors(instrs)
            live_after_block = set()
            for s in succs:
                live_after_block |= live_before.get(s, set())

            live = set(live_after_block)
            for node in reversed(instrs):
                live = (live - write_vars(node)) | read_vars(node)

            if live != live_before[label]:
                live_before[label] = live
                changed = True

    # Compute per-instruction live-after sets
    result = {}
    for label, instrs in blocks.items():
        succs = _block_successors(instrs)
        live_after_block = set()
        for s in succs:
            live_after_block |= live_before.get(s, set())

        per_instr = []
        live = set(live_after_block)
        for node in reversed(instrs):
            per_instr.append(frozenset(live))
            live = (live - write_vars(node)) | read_vars(node)

        result[label] = list(reversed(per_instr))
    return result


# ── 2. Interference graph ─────────────────────────────────────────────

def build_interference(program, live_after_map):
    """Build undirected interference graph.

    Special rule: ``movq s, d`` does NOT create interference between *s*
    and *d* (they can share a register).
    """
    graph = UndirectedAdjList()

    for label, instrs in program.body.items():
        la_list = live_after_map[label]
        for i, node in enumerate(instrs):
            la = la_list[i]
            for d in write_vars(node):
                if not isinstance(d, (Variable, Reg, ByteReg)):
                    continue
                graph.add_vertex(d)
                for v in la:
                    if not isinstance(v, (Variable, Reg, ByteReg)):
                        continue
                    if v == d:
                        continue
                    # movq non-interference rule
                    if isinstance(node, Instr) and node.instr in ('movq', 'movzbq'):
                        src = node.args[0]
                        if v == src:
                            continue
                    graph.add_vertex(v)
                    if not graph.has_edge(d, v):
                        graph.add_edge(d, v)
    return graph


# ── 3. Move graph ─────────────────────────────────────────────────────

def build_move_graph(program):
    """Edges between source and dest of ``movq`` for move biasing."""
    graph = UndirectedAdjList()
    for instrs in program.body.values():
        for node in instrs:
            if isinstance(node, Instr) and node.instr == 'movq':
                s, d = node.args
                if isinstance(s, (Variable, Reg)) and isinstance(d, (Variable, Reg)):
                    graph.add_vertex(s)
                    graph.add_vertex(d)
                    if not graph.has_edge(s, d):
                        graph.add_edge(s, d)
    return graph


# ── 4. Graph coloring (DSATUR) ─────────────────────────────────────────

def color_graph(interference, move_graph, variables):
    """DSATUR coloring with optional move biasing.

    Pre-colored ``Reg`` nodes keep their colours.  Variables receive
    colours 0..NUM_COLORS-1 (physical registers) or ≥ NUM_COLORS (spills).
    """
    coloring = {}
    saturation = {}  # vertex → set of colours used by neighbours

    # Pre-colour Reg / ByteReg nodes
    for v in interference.vertices():
        saturation[v] = set()
        if isinstance(v, (Reg, ByteReg)):
            c = REG_COLOR.get(v.id)
            if c is not None:
                coloring[v] = c

    # Propagate pre-colours into saturation sets
    for v, c in coloring.items():
        for u in interference.adjacent(v):
            saturation.setdefault(u, set()).add(c)

    # Ensure every variable is present
    uncolored = set()
    for v in variables:
        if v not in coloring:
            interference.add_vertex(v)
            saturation.setdefault(v, set())
            uncolored.add(v)
    for v in interference.vertices():
        if isinstance(v, Variable) and v not in coloring:
            uncolored.add(v)
            saturation.setdefault(v, set())

    # Greedy DSATUR loop
    while uncolored:
        # Pick vertex with max saturation; break ties by degree
        best, best_sat, best_deg = None, -1, -1
        for v in uncolored:
            s = len(saturation.get(v, set()))
            d = len(list(interference.adjacent(v)))
            if s > best_sat or (s == best_sat and d > best_deg):
                best, best_sat, best_deg = v, s, d

        v = best
        uncolored.discard(v)

        used = saturation.get(v, set())

        # Move biasing: prefer colour of a move-related neighbour
        preferred = set()
        if v in move_graph.out:
            for u in move_graph.out[v]:
                if u in coloring:
                    c = coloring[u]
                    if c >= 0 and c not in used:
                        preferred.add(c)

        color = None
        for c in sorted(preferred):
            if c not in used:
                color = c
                break
        if color is None:
            color = 0
            while color in used:
                color += 1

        coloring[v] = color

        # Update neighbours' saturation
        for u in interference.adjacent(v):
            saturation.setdefault(u, set()).add(color)

    return coloring


# ── 5. Assign homes ───────────────────────────────────────────────────

def assign_homes(program, coloring):
    """Replace every ``Variable`` with ``Reg`` or ``Deref('rbp', …)``."""

    def _replace(a):
        if not isinstance(a, Variable):
            return a
        c = coloring.get(a, 0)
        if c < NUM_COLORS:
            return Reg(COLOR_TO_REG[c])
        return Deref('rbp', -8 * (c - NUM_COLORS + 1))

    new_body = {}
    for label, instrs in program.body.items():
        new_instrs = []
        for node in instrs:
            if isinstance(node, Instr):
                new_instrs.append(Instr(node.instr,
                                        tuple(_replace(a) for a in node.args)))
            else:
                new_instrs.append(node)
        new_body[label] = new_instrs
    return X86Program(new_body)


# ── 6. Patch instructions ─────────────────────────────────────────────

def patch_instructions(program):
    """Fix x86 constraint violations; remove trivial ``movq %r, %r``."""
    new_body = {}
    for label, instrs in program.body.items():
        patched = []
        for node in instrs:
            if not isinstance(node, Instr):
                patched.append(node)
                continue

            op, args = node.instr, node.args

            # Remove trivial movq
            if op == 'movq' and len(args) == 2 and args[0] == args[1]:
                continue

            # Two-operand mem-to-mem
            if op in ('movq', 'movzbq', 'addq', 'subq', 'xorq', 'cmpq') \
                    and len(args) == 2:
                a, b = args
                if isinstance(a, Deref) and isinstance(b, Deref):
                    patched.append(Instr('movq', (a, Reg('rax'))))
                    patched.append(Instr(op, (Reg('rax'), b)))
                    continue

            # cmpq cannot have Immediate as second operand in real x86
            if op == 'cmpq' and len(args) == 2 and isinstance(args[1], Immediate):
                patched.append(Instr('movq', (args[1], Reg('rax'))))
                patched.append(Instr('cmpq', (args[0], Reg('rax'))))
                continue

            # movzbq destination must be a register
            if op == 'movzbq' and len(args) == 2 and isinstance(args[1], Deref):
                patched.append(Instr('movzbq', (args[0], Reg('rax'))))
                patched.append(Instr('movq', (Reg('rax'), args[1])))
                continue

            patched.append(node)
        new_body[label] = patched
    return X86Program(new_body)


# ── 7. Prelude & conclusion ───────────────────────────────────────────

def prelude_and_conclusion(program, num_spills, used_callee):
    """Add ``main`` (prologue) and ``conclusion`` (epilogue) blocks.

    Callee-saved registers are saved/restored via movq into the frame
    (below the spill slots).
    """
    num_callee = len(used_callee)
    total_slots = num_spills + num_callee
    frame_size = 8 * total_slots
    # Align to 16 bytes (pushq rbp already used 8, so frame must be
    # even multiple of 8 to end on 16-byte alignment)
    if frame_size % 16 != 0:
        frame_size += 8

    callee_list = sorted(used_callee)  # deterministic order

    # Prelude
    prelude = [
        Instr('pushq', (Reg('rbp'),)),
        Instr('movq', (Reg('rsp'), Reg('rbp'))),
    ]
    if frame_size > 0:
        prelude.append(Instr('subq', (Immediate(frame_size), Reg('rsp'))))
    for idx, r in enumerate(callee_list):
        offset = -8 * (num_spills + idx + 1)
        prelude.append(Instr('movq', (Reg(r), Deref('rbp', offset))))
    prelude.append(Jump('start'))

    # Conclusion
    conclusion = []
    for idx, r in enumerate(callee_list):
        offset = -8 * (num_spills + idx + 1)
        conclusion.append(Instr('movq', (Deref('rbp', offset), Reg(r))))
    if frame_size > 0:
        conclusion.append(Instr('addq', (Immediate(frame_size), Reg('rsp'))))
    conclusion.append(Instr('popq', (Reg('rbp'),)))
    conclusion.append(Instr('retq', ()))

    new_body = dict(program.body)
    new_body['main'] = prelude
    new_body['conclusion'] = conclusion
    return X86Program(new_body)


# ── Collect variables ──────────────────────────────────────────────────

def _collect_variables(program):
    vs = set()
    for instrs in program.body.values():
        for node in instrs:
            if isinstance(node, Instr):
                for a in node.args:
                    if isinstance(a, Variable):
                        vs.add(a)
    return vs


# ── Top-level entry point ─────────────────────────────────────────────

def allocate_registers(program: X86Program) -> X86Program:
    program = copy.deepcopy(program)

    live_after = uncover_live(program)
    interference = build_interference(program, live_after)
    move_graph = build_move_graph(program)
    variables = _collect_variables(program)
    coloring = color_graph(interference, move_graph, variables)

    # Determine spill count and callee-saved usage
    num_spills = 0
    used_callee = set()
    for v, c in coloring.items():
        if not isinstance(v, Variable):
            continue
        if c >= NUM_COLORS:
            num_spills = max(num_spills, c - NUM_COLORS + 1)
        elif ALLOCATABLE_REGS[c] in CALLEE_SAVED:
            used_callee.add(ALLOCATABLE_REGS[c])

    program = assign_homes(program, coloring)
    program = patch_instructions(program)
    program = prelude_and_conclusion(program, num_spills, used_callee)
    return program
