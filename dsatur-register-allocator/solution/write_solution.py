"""
Generate the register allocator and assembly emitter implementations.
"""
import textwrap, pathlib

reg_alloc_code = textwrap.dedent(r'''
# Auto-generated register allocator implementation.
import sys
sys.path.insert(0, "/opt/regalloc")
sys.path.insert(0, "/app")

from ir import (
    X86Program, Instr, Callq, Jump, JumpIf,
    Immediate, Register, Variable, Deref,
    instr_reads, instr_writes,
    CALLER_SAVED, CALLEE_SAVED, ALLOCATABLE, NUM_REGS,
    REG_COLOR, color_to_location,
)
from graph import UndirectedAdjList


class AllocResult:
    def __init__(self, program, stack_size, used_callee_saved):
        self.program = program
        self.stack_size = stack_size
        self.used_callee_saved = used_callee_saved


def build_cfg(program):
    succ = {}
    pred = {lbl: set() for lbl in program.blocks}
    for lbl, instrs in program.blocks.items():
        targets = set()
        for ins in instrs:
            if isinstance(ins, Jump):
                targets.add(ins.label)
            elif isinstance(ins, JumpIf):
                targets.add(ins.label)
        succ[lbl] = targets
        for t in targets:
            if t in pred:
                pred[t].add(lbl)
    return succ, pred


def analyze_liveness(program, cfg_succ, cfg_pred):
    live_before_block = {lbl: set() for lbl in program.blocks}
    changed = True
    while changed:
        changed = False
        for lbl in program.blocks:
            instrs = program.blocks[lbl]
            live_after_block = set()
            for s in cfg_succ.get(lbl, set()):
                live_after_block |= live_before_block.get(s, set())
            live = live_after_block.copy()
            for ins in reversed(instrs):
                live = (live - instr_writes(ins)) | instr_reads(ins)
            if live != live_before_block[lbl]:
                live_before_block[lbl] = live
                changed = True

    result = {}
    for lbl in program.blocks:
        instrs = program.blocks[lbl]
        live_after_block = set()
        for s in cfg_succ.get(lbl, set()):
            live_after_block |= live_before_block.get(s, set())
        la_rev = []
        live = live_after_block
        for ins in reversed(instrs):
            la_rev.append(frozenset(live))
            live = (live - instr_writes(ins)) | instr_reads(ins)
        la_rev.reverse()
        result[lbl] = la_rev
    return result


def _is_loc_move(ins):
    return (isinstance(ins, Instr) and ins.name == "movq"
            and isinstance(ins.args[0], (Variable, Register))
            and isinstance(ins.args[1], (Variable, Register)))


def build_interference_graph(program, live_after_sets):
    g = UndirectedAdjList()
    for lbl, instrs in program.blocks.items():
        la_sets = live_after_sets[lbl]
        for i, ins in enumerate(instrs):
            la = la_sets[i]
            ws = instr_writes(ins)
            is_move = _is_loc_move(ins)
            for d in ws:
                if not isinstance(d, (Variable, Register)):
                    continue
                g.add_vertex(d)
                for v in la:
                    if not isinstance(v, (Variable, Register)):
                        continue
                    if v == d:
                        continue
                    if is_move and v == ins.args[0]:
                        continue
                    g.add_vertex(v)
                    g.add_edge(d, v)
    return g


def build_move_graph(program):
    g = UndirectedAdjList()
    for instrs in program.blocks.values():
        for ins in instrs:
            if _is_loc_move(ins):
                src, dst = ins.args[0], ins.args[1]
                if src != dst:
                    g.add_vertex(src)
                    g.add_vertex(dst)
                    g.add_edge(src, dst)
    return g


def color_graph(interference, move_graph, variables):
    color = {}
    saturation = {v: set() for v in interference.vertices()}

    for v in interference.vertices():
        if isinstance(v, Register) and v in REG_COLOR:
            color[v] = REG_COLOR[v]

    for v, c in list(color.items()):
        for u in interference.adjacent(v):
            if u not in color:
                saturation[u].add(c)

    worklist = {v for v in interference.vertices() if isinstance(v, Variable)}

    while worklist:
        best = None
        best_sat = -1
        best_move = -1
        for v in worklist:
            s = len(saturation[v])
            m = 0
            try:
                for u in move_graph.adjacent(v):
                    if u in color:
                        m += 1
            except Exception:
                pass
            if s > best_sat or (s == best_sat and m > best_move):
                best = v
                best_sat = s
                best_move = m

        unavail = set()
        for nb in interference.adjacent(best):
            if nb in color:
                unavail.add(color[nb])

        preferred = set()
        try:
            for nb in move_graph.adjacent(best):
                if nb in color and color[nb] >= 0 and color[nb] not in unavail:
                    preferred.add(color[nb])
        except Exception:
            pass

        if preferred:
            c = min(preferred)
        else:
            c = 0
            while c in unavail:
                c += 1

        color[best] = c
        for nb in interference.adjacent(best):
            if nb in worklist:
                saturation[nb].add(c)
        worklist.remove(best)

    return color


def _replace_arg(a, cmap):
    if isinstance(a, Variable):
        return color_to_location(cmap[a])
    return a


def allocate_registers(program):
    cfg_s, cfg_p = build_cfg(program)
    la = analyze_liveness(program, cfg_s, cfg_p)
    ig = build_interference_graph(program, la)
    mg = build_move_graph(program)
    variables = {v for v in ig.vertices() if isinstance(v, Variable)}
    cmap = color_graph(ig, mg, variables)

    max_color = max((cmap[v] for v in variables if v in cmap), default=-1)
    num_spills = max(0, max_color - NUM_REGS + 1)
    stack_bytes = num_spills * 8
    if stack_bytes % 16 != 0:
        stack_bytes += 8

    cs_set = set(CALLEE_SAVED)
    used_cs = []
    for v in variables:
        c = cmap.get(v, -1)
        if 0 <= c < NUM_REGS:
            rname = ALLOCATABLE[c]
            if rname in cs_set and rname not in used_cs:
                used_cs.append(rname)

    new_blocks = {}
    for lbl, instrs in program.blocks.items():
        new_instrs = []
        for ins in instrs:
            if isinstance(ins, Instr):
                new_instrs.append(Instr(ins.name, [_replace_arg(a, cmap) for a in ins.args]))
            else:
                new_instrs.append(ins)
        new_blocks[lbl] = new_instrs

    return AllocResult(X86Program(new_blocks), stack_bytes, used_cs)
''').lstrip()

emit_asm_code = textwrap.dedent(r'''
# Auto-generated assembly emitter implementation.
import sys
sys.path.insert(0, "/opt/regalloc")
sys.path.insert(0, "/app")

from ir import Immediate, Register, Deref, Instr, Callq, Jump, JumpIf


def format_operand(op):
    if isinstance(op, Immediate):
        return f"${op.value}"
    if isinstance(op, Register):
        return f"%{op.name}"
    if isinstance(op, Deref):
        return f"{op.offset}(%{op.reg})"
    raise ValueError(f"Unknown operand: {type(op).__name__}")


def emit_program(program, stack_size, used_callee_saved):
    lines = []
    lines.append("    .text")
    lines.append("    .globl main")
    lines.append("    .type main, @function")
    lines.append("main:")
    lines.append("    pushq %rbp")
    lines.append("    movq %rsp, %rbp")

    n_cs = len(used_callee_saved)
    # Frame layout: spill slots at rbp-8 .. rbp-stack_size,
    # callee-saved storage below that, plus alignment padding.
    frame_size = stack_size + 8 * n_cs
    if frame_size % 16 != 0:
        frame_size += 8

    if frame_size > 0:
        lines.append(f"    subq ${frame_size}, %rsp")

    # Save callee-saved registers below the spill area
    for i, reg in enumerate(used_callee_saved):
        offset = -(stack_size + 8 * (i + 1))
        lines.append(f"    movq %{reg}, {offset}(%rbp)")

    # Linearize blocks: start first, conclusion last
    block_order = []
    if "start" in program.blocks:
        block_order.append("start")
    for label in program.blocks:
        if label not in ("start", "conclusion"):
            block_order.append(label)
    if "conclusion" in program.blocks:
        block_order.append("conclusion")

    for label in block_order:
        instrs = program.blocks[label]
        lines.append(f".L{label}:")

        if label == "conclusion":
            # Epilogue: restore callee-saved, tear down frame, return
            for i, reg in enumerate(used_callee_saved):
                offset = -(stack_size + 8 * (i + 1))
                lines.append(f"    movq {offset}(%rbp), %{reg}")
            lines.append("    movq %rbp, %rsp")
            lines.append("    popq %rbp")
            lines.append("    ret")
            continue

        for ins in instrs:
            if isinstance(ins, Instr):
                args_str = ", ".join(format_operand(a) for a in ins.args)
                lines.append(f"    {ins.name} {args_str}")
            elif isinstance(ins, Callq):
                lines.append(f"    call {ins.func}")
            elif isinstance(ins, Jump):
                lines.append(f"    jmp .L{ins.label}")
            elif isinstance(ins, JumpIf):
                lines.append(f"    j{ins.cc} .L{ins.label}")

    lines.append("")
    return "\n".join(lines)
''').lstrip()

pathlib.Path("/app/register_allocator.py").write_text(reg_alloc_code)
pathlib.Path("/app/emit_asm.py").write_text(emit_asm_code)
print("register_allocator.py and emit_asm.py written successfully")
