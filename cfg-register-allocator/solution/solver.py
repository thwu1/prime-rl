"""Complete register allocator for X86-64 CFG programs.

Implements:
  1. Backward dataflow liveness analysis with fixed-point iteration
  2. Interference graph construction (with movq src-dst exception)
  3. DSATUR graph coloring with move biasing
  4. Spilling to stack when registers exhausted
  5. Trivial movq elimination
"""
import sys
sys.path.insert(0, '/app')
from ir import (Imm, Reg, Var, Deref, Instr, X86Program,
                CALLER_SAVED, CALLEE_SAVED, ALLOCATABLE, ARG_REGS,
                reads_of, writes_of, block_successors)
from framework import UndirectedAdjList

# Mapping from register names to pre-assigned colours.
# Allocatable registers get colours 0..11; reserved registers get
# negative colours so they can never be assigned to a variable.
_REG_COLOR = {}
for _i, _r in enumerate(ALLOCATABLE):
    _REG_COLOR[_r] = _i
_REG_COLOR['rax'] = -1
_REG_COLOR['rsp'] = -2
_REG_COLOR['rbp'] = -3
_REG_COLOR['r15'] = -4
_REG_COLOR['al'] = -1          # al aliases rax


def allocate_registers(program):
    """Replace every Var in *program* with a Reg or stack Deref.

    Returns a new X86Program with ``stack_space`` set to the number
    of bytes used for spilled variables (16-byte aligned).
    """
    blocks = program.blocks

    # ------------------------------------------------------------------
    # 1. Block successor map
    # ------------------------------------------------------------------
    succ = {label: block_successors(instrs)
            for label, instrs in blocks.items()}

    # ------------------------------------------------------------------
    # 2. Liveness analysis — fixed-point iteration
    # ------------------------------------------------------------------
    live_before_block = {label: set() for label in blocks}

    _JUMP_OPS = frozenset(('jmp', 'je', 'jne', 'jl', 'jle', 'jg', 'jge'))

    changed = True
    while changed:
        changed = False
        for label in blocks:
            # live-out of block = ∪ live-in of successors
            live_out = set()
            for s in succ[label]:
                if s == 'conclusion':
                    live_out.add(Reg('rax'))
                elif s in live_before_block:
                    live_out |= live_before_block[s]

            # walk backwards through the block
            live = set(live_out)
            for instr in reversed(blocks[label]):
                if instr.op not in _JUMP_OPS:
                    live = (live - writes_of(instr)) | reads_of(instr)

            if live != live_before_block[label]:
                live_before_block[label] = live
                changed = True

    # 2b. Per-instruction live-after sets (needed for interference)
    live_after_map = {}  # (label, idx) → set
    for label in blocks:
        live_out = set()
        for s in succ[label]:
            if s == 'conclusion':
                live_out.add(Reg('rax'))
            elif s in live_before_block:
                live_out |= live_before_block[s]

        live = set(live_out)
        instrs = blocks[label]
        for idx in range(len(instrs) - 1, -1, -1):
            live_after_map[(label, idx)] = frozenset(live)
            if instrs[idx].op not in _JUMP_OPS:
                live = (live - writes_of(instrs[idx])) | reads_of(instrs[idx])

    # ------------------------------------------------------------------
    # 3. Build interference graph + move graph
    # ------------------------------------------------------------------
    interference = UndirectedAdjList()
    move_graph = UndirectedAdjList()

    # Collect every Reg/Var that appears anywhere (including implicit
    # reads/writes such as caller-saved registers clobbered by callq)
    all_locs = set()
    for instrs in blocks.values():
        for instr in instrs:
            for a in instr.args:
                if isinstance(a, (Reg, Var)):
                    all_locs.add(a)
            all_locs |= reads_of(instr)
            all_locs |= writes_of(instr)
    for la in live_after_map.values():
        all_locs |= la
    for lb in live_before_block.values():
        all_locs |= lb

    for loc in all_locs:
        interference.add_vertex(loc)
        move_graph.add_vertex(loc)

    for label in blocks:
        instrs = blocks[label]
        for idx, instr in enumerate(instrs):
            la = live_after_map.get((label, idx), frozenset())
            op = instr.op

            if (op == 'movq'
                    and isinstance(instr.args[0], (Reg, Var))
                    and isinstance(instr.args[1], (Reg, Var))):
                src, dst = instr.args[0], instr.args[1]
                for loc in la:
                    if loc != dst and loc != src:
                        interference.add_edge(dst, loc)
                move_graph.add_edge(src, dst)

            elif op not in _JUMP_OPS:
                for d in writes_of(instr):
                    if isinstance(d, (Reg, Var)):
                        for loc in la:
                            if loc != d:
                                interference.add_edge(d, loc)

    # ------------------------------------------------------------------
    # 4. DSATUR graph colouring with move biasing
    # ------------------------------------------------------------------
    colour = {}

    # Pre-colour every physical register
    for loc in all_locs:
        if isinstance(loc, Reg):
            colour[loc] = _REG_COLOR.get(loc.name, -100)

    # Variables still to colour
    uncoloured = [loc for loc in all_locs if isinstance(loc, Var)]

    # Saturation sets
    saturation = {loc: set() for loc in all_locs}
    for loc in all_locs:
        if loc in colour:
            for adj in interference.adjacent(loc):
                saturation[adj].add(colour[loc])

    while uncoloured:
        # Pick vertex with max |saturation|;
        # break ties by preferring move-related vertices.
        best = None
        best_sat = -1
        best_mv = -1
        for v in uncoloured:
            s = len(saturation[v])
            mv = 0
            for adj in move_graph.adjacent(v):
                if adj in colour and colour[adj] >= 0 \
                        and colour[adj] not in saturation[v]:
                    mv += 1
            if (s > best_sat) or (s == best_sat and mv > best_mv):
                best = v
                best_sat = s
                best_mv = mv

        # Choose colour — prefer a move-related colour if available
        chosen = None
        for adj in move_graph.adjacent(best):
            if adj in colour:
                c = colour[adj]
                if c >= 0 and c not in saturation[best]:
                    if chosen is None or c < chosen:
                        chosen = c

        if chosen is None:
            chosen = 0
            while chosen in saturation[best]:
                chosen += 1

        colour[best] = chosen
        uncoloured.remove(best)

        for adj in interference.adjacent(best):
            saturation[adj].add(chosen)

    # ------------------------------------------------------------------
    # 5. Map colours → physical locations
    # ------------------------------------------------------------------
    num_alloc = len(ALLOCATABLE)

    def _colour_to_loc(c):
        if 0 <= c < num_alloc:
            return Reg(ALLOCATABLE[c])
        spill_idx = c - num_alloc
        return Deref('rbp', -8 * (spill_idx + 1))

    var_map = {}
    max_spill = 0
    for loc, c in colour.items():
        if isinstance(loc, Var):
            var_map[loc] = _colour_to_loc(c)
            if c >= num_alloc:
                max_spill = max(max_spill, c - num_alloc + 1)

    stack_bytes = max_spill * 8
    if stack_bytes % 16 != 0:
        stack_bytes += 16 - (stack_bytes % 16)

    # ------------------------------------------------------------------
    # 6. Rewrite & patch trivial movq
    # ------------------------------------------------------------------
    def _rw(a):
        if isinstance(a, Var):
            return var_map[a]
        return a

    new_blocks = {}
    for label, instrs in blocks.items():
        new_instrs = []
        for instr in instrs:
            new_args = [_rw(a) if isinstance(a, (Reg, Var, Imm, Deref))
                        else a
                        for a in instr.args]
            ni = Instr(instr.op, new_args)
            # Drop trivial movq %X, %X  /  movq off(%r), off(%r)
            if (ni.op == 'movq' and len(ni.args) >= 2
                    and isinstance(ni.args[0], (Reg, Deref))
                    and ni.args[0] == ni.args[1]):
                continue
            new_instrs.append(ni)
        new_blocks[label] = new_instrs

    return X86Program(new_blocks, stack_bytes)
