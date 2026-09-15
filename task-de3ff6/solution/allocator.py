
"""
Register allocator for pseudo-x86 programs.

Implements:
  1. Backward dataflow liveness analysis with fixed-point iteration
  2. Interference graph construction with pre-colored register nodes
  3. DSATUR graph coloring with move biasing
  4. Spill code generation (variables -> stack slots)
  5. Instruction patching (remove trivial moves, fix two-memory-op violations)
"""

from graph import UndirectedAdjList

# Registers available for allocation (colors 0..11)
ALLOCATABLE_REGS = [
    'rbx', 'rcx', 'rdx', 'rsi', 'rdi',
    'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14',
]
NUM_ALLOC = len(ALLOCATABLE_REGS)

# Caller-saved registers that are ALSO in the allocatable set
CALLER_SAVED_ALLOC = {'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11'}

# Map allocatable register name -> color
REG_COLOR = {r: i for i, r in enumerate(ALLOCATABLE_REGS)}

# x86-64 argument passing registers (System V ABI)
ARG_REGS = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']


# ---------------------------------------------------------------------------
# Instruction analysis helpers
# ---------------------------------------------------------------------------

def _arg_reads(arg):
    """Variables or registers read by an argument."""
    if not isinstance(arg, tuple):
        return set()
    if arg[0] == 'var':
        return {arg[1]}
    elif arg[0] == 'reg':
        return {arg[1]}
    elif arg[0] == 'deref':
        return {arg[1]}
    return set()


def _arg_writes(arg):
    """Variables or registers written by an argument (not memory stores)."""
    if not isinstance(arg, tuple):
        return set()
    if arg[0] == 'var':
        return {arg[1]}
    elif arg[0] == 'reg':
        return {arg[1]}
    # deref writes to memory, not to a register
    return set()


def reads_of(instr):
    """Set of names (variables / registers) read by instruction."""
    op = instr[0]
    r = set()
    if op in ('movq', 'movzbq'):
        r |= _arg_reads(instr[1])
    elif op in ('addq', 'subq', 'xorq'):
        r |= _arg_reads(instr[1])
        r |= _arg_reads(instr[2])
    elif op == 'negq':
        r |= _arg_reads(instr[1])
    elif op == 'cmpq':
        r |= _arg_reads(instr[1])
        r |= _arg_reads(instr[2])
    elif op == 'callq':
        arity = instr[2] if len(instr) > 2 else 0
        for i in range(min(arity, len(ARG_REGS))):
            r.add(ARG_REGS[i])
    elif op == 'pushq':
        r |= _arg_reads(instr[1])
    # sete/setl/..., jmp, jCC: no register reads modeled
    return r


def writes_of(instr):
    """Set of names (variables / registers) written by instruction."""
    op = instr[0]
    w = set()
    if op in ('movq', 'movzbq'):
        w |= _arg_writes(instr[2])
    elif op in ('addq', 'subq', 'xorq'):
        w |= _arg_writes(instr[2])
    elif op == 'negq':
        w |= _arg_writes(instr[1])
    elif op == 'callq':
        # caller-saved registers are clobbered
        w |= {'rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11'}
    elif op in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
        w |= _arg_writes(instr[1])
    elif op == 'popq':
        w |= _arg_writes(instr[1])
    # cmpq: writes EFLAGS only (not modeled)
    # jmp, jCC: no writes
    return w


def get_jump_targets(instr):
    """Return list of label strings this instruction may jump to."""
    op = instr[0]
    if op in ('jmp', 'je', 'jne', 'jl', 'jle', 'jg', 'jge'):
        return [instr[1]]
    return []


def is_conditional_jump(instr):
    return instr[0] in ('je', 'jne', 'jl', 'jle', 'jg', 'jge')


def is_movq(instr):
    return instr[0] == 'movq'


# ---------------------------------------------------------------------------
# Pass 1: Liveness analysis (backward dataflow, fixed-point)
# ---------------------------------------------------------------------------

def _block_successors(blocks):
    """Map each block label to its set of successor labels."""
    succs = {}
    for label, instrs in blocks.items():
        s = set()
        for instr in instrs:
            for t in get_jump_targets(instr):
                if t != 'conclusion':
                    s.add(t)
        succs[label] = s
    return succs


def uncover_live(blocks):
    """Compute live-after sets for every instruction in every block.

    Returns dict: label -> [set(), set(), ...] (one set per instruction).
    Uses fixed-point iteration to handle loops (back edges in CFG).
    """
    succs = _block_successors(blocks)

    # live_in[label] = set of names live at the START of the block
    live_in = {label: set() for label in blocks}

    changed = True
    while changed:
        changed = False
        for label in blocks:
            instrs = blocks[label]

            # live_out = union of live_in of successor blocks
            live_out = set()
            for s in succs.get(label, set()):
                live_out |= live_in[s]

            # Walk backward through block computing live sets
            live = live_out.copy()
            for i in range(len(instrs) - 1, -1, -1):
                instr = instrs[i]
                # For conditional jumps, union in target's live_in
                if is_conditional_jump(instr):
                    for t in get_jump_targets(instr):
                        if t != 'conclusion' and t in live_in:
                            live = live | live_in[t]
                live = (live - writes_of(instr)) | reads_of(instr)

            if live != live_in[label]:
                live_in[label] = live
                changed = True

    # Now compute the actual live-after sets for each instruction
    live_after_map = {}
    for label in blocks:
        instrs = blocks[label]
        live_out = set()
        for s in succs.get(label, set()):
            live_out |= live_in[s]

        la_sets = [None] * len(instrs)
        live = live_out.copy()
        for i in range(len(instrs) - 1, -1, -1):
            instr = instrs[i]
            if is_conditional_jump(instr):
                for t in get_jump_targets(instr):
                    if t != 'conclusion' and t in live_in:
                        live = live | live_in[t]
            la_sets[i] = live.copy()
            live = (live - writes_of(instr)) | reads_of(instr)

        live_after_map[label] = la_sets

    return live_after_map


# ---------------------------------------------------------------------------
# Pass 2: Build interference and move graphs
# ---------------------------------------------------------------------------

def _collect_variables(blocks):
    """Return set of all variable names used in blocks."""
    variables = set()
    for instrs in blocks.values():
        for instr in instrs:
            for arg in instr[1:]:
                if isinstance(arg, tuple) and arg[0] == 'var':
                    variables.add(arg[1])
    return variables


def build_graphs(blocks, live_after_map):
    """Build interference graph and move graph.

    The interference graph contains:
      - All variables
      - Pre-colored allocatable registers that appear in live sets or writes

    Returns (interference_graph, move_graph).
    """
    variables = _collect_variables(blocks)
    interference = UndirectedAdjList()
    move_graph = UndirectedAdjList()

    # Add all variables as vertices
    for v in variables:
        interference.add_vertex(v)
        move_graph.add_vertex(v)

    # Determine which registers need to be in the graph
    # (any allocatable register that is written by an instruction
    # or appears in a live-after set)
    reg_nodes = set()
    for label, instrs in blocks.items():
        for i, instr in enumerate(instrs):
            for w in writes_of(instr):
                if w in REG_COLOR:
                    reg_nodes.add(w)
            for v in live_after_map[label][i]:
                if v in REG_COLOR:
                    reg_nodes.add(v)

    for r in reg_nodes:
        interference.add_vertex(r)

    # Build edges
    for label, instrs in blocks.items():
        for i, instr in enumerate(instrs):
            la = live_after_map[label][i]
            W = writes_of(instr)

            if is_movq(instr):
                src_names = _arg_reads(instr[1])
                # Move graph edge between src and dst (if both are variables)
                dst_names = _arg_writes(instr[2])
                for s in src_names:
                    for d in dst_names:
                        if s != d and s in variables and d in variables:
                            move_graph.add_edge(s, d)
                        # Also record moves between variables and registers
                        # for move biasing
                        if s != d:
                            if (s in variables and d in REG_COLOR) or \
                               (d in variables and s in REG_COLOR):
                                move_graph.add_vertex(s)
                                move_graph.add_vertex(d)
                                move_graph.add_edge(s, d)

                # For movq, don't add interference between src and dst
                for d in W:
                    if d not in interference.vertices():
                        continue
                    for v in la:
                        if v not in interference.vertices():
                            continue
                        if v != d and v not in src_names:
                            interference.add_edge(d, v)
            else:
                for d in W:
                    if d not in interference.vertices():
                        continue
                    for v in la:
                        if v not in interference.vertices():
                            continue
                        if v != d:
                            interference.add_edge(d, v)

    return interference, move_graph


# ---------------------------------------------------------------------------
# Pass 3: Graph coloring (DSATUR with move biasing)
# ---------------------------------------------------------------------------

def color_graph(interference, move_graph, variables):
    """Assign colors to variables using DSATUR with move biasing.

    Pre-colored registers keep their fixed color.
    Returns dict: name -> color (int).
    """
    color = {}
    saturation = {v: set() for v in interference.vertices()}

    # Pre-color register nodes
    for v in interference.vertices():
        if v in REG_COLOR:
            color[v] = REG_COLOR[v]

    # Update saturation from pre-colored neighbors
    for v in interference.vertices():
        if v in color:
            for adj in interference.adjacent(v):
                saturation[adj].add(color[v])

    # Worklist: only variables (not pre-colored registers)
    worklist = set(v for v in variables if v in interference.vertices())

    while worklist:
        # Pick vertex with maximum saturation; break ties with move biasing
        best = None
        best_sat = -1
        best_move_pref = False

        for v in worklist:
            sat = len(saturation[v])
            # Check if v has a move-related neighbor that's been colored
            # with a color not in saturation
            has_pref = False
            if v in move_graph.vertices():
                for adj in move_graph.adjacent(v):
                    if adj in color and color[adj] not in saturation[v]:
                        has_pref = True
                        break

            if sat > best_sat or \
               (sat == best_sat and has_pref and not best_move_pref) or \
               (sat == best_sat and has_pref == best_move_pref and
                (best is None or v < best)):
                best = v
                best_sat = sat
                best_move_pref = has_pref

        v = best
        worklist.remove(v)

        # Try to use a color from a move-related, already-colored neighbor
        preferred = None
        if v in move_graph.vertices():
            for adj in move_graph.adjacent(v):
                if adj in color and color[adj] not in saturation[v]:
                    preferred = color[adj]
                    break

        if preferred is not None:
            c = preferred
        else:
            # Pick lowest available color
            c = 0
            while c in saturation[v]:
                c += 1

        color[v] = c

        # Update saturation of neighbors
        for adj in interference.adjacent(v):
            saturation[adj].add(c)

    return color


# ---------------------------------------------------------------------------
# Pass 4: Apply allocation (replace vars with regs / stack slots)
# ---------------------------------------------------------------------------

def _color_to_home(c):
    """Map color to a register or stack deref argument."""
    if c < NUM_ALLOC:
        return ('reg', ALLOCATABLE_REGS[c])
    else:
        offset = -8 * (c - NUM_ALLOC + 1)
        return ('deref', 'rbp', offset)


def apply_allocation(blocks, coloring):
    """Replace all ('var', name) args with their allocated homes.

    Returns (new_blocks, num_stack_slots).
    """
    num_stack_slots = 0
    new_blocks = {}

    for label, instrs in blocks.items():
        new_instrs = []
        for instr in instrs:
            new_parts = [instr[0]]
            for arg in instr[1:]:
                if isinstance(arg, tuple) and arg[0] == 'var':
                    c = coloring[arg[1]]
                    home = _color_to_home(c)
                    new_parts.append(home)
                    if home[0] == 'deref':
                        slot = abs(home[2]) // 8
                        num_stack_slots = max(num_stack_slots, slot)
                else:
                    new_parts.append(arg)
            new_instrs.append(tuple(new_parts))
        new_blocks[label] = new_instrs

    return new_blocks, num_stack_slots


# ---------------------------------------------------------------------------
# Pass 5: Patch instructions
# ---------------------------------------------------------------------------

def patch_instructions(blocks):
    """Fix x86 constraint violations:
    1. Remove trivial moves (movq X, X)
    2. Fix two-memory-operand instructions using %rax as temp
    """
    new_blocks = {}
    for label, instrs in blocks.items():
        new_instrs = []
        for instr in instrs:
            op = instr[0]

            # Remove trivial movq
            if op == 'movq' and len(instr) == 3 and instr[1] == instr[2]:
                continue

            # Fix two memory operands
            if op in ('movq', 'addq', 'subq', 'xorq', 'cmpq') and len(instr) == 3:
                src_mem = isinstance(instr[1], tuple) and instr[1][0] == 'deref'
                dst_mem = isinstance(instr[2], tuple) and instr[2][0] == 'deref'
                if src_mem and dst_mem:
                    # Load src into rax, then do op rax, dst
                    new_instrs.append(('movq', instr[1], ('reg', 'rax')))
                    new_instrs.append((op, ('reg', 'rax'), instr[2]))
                    continue

            new_instrs.append(instr)
        new_blocks[label] = new_instrs
    return new_blocks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def allocate_registers(program):
    """Allocate registers for a pseudo-x86 program.

    Args:
        program: dict with 'blocks' mapping labels to instruction lists.

    Returns:
        dict with 'blocks' containing allocated x86 (no variables).
    """
    blocks = program['blocks']

    # 1. Liveness analysis
    live_after = uncover_live(blocks)

    # 2. Build interference and move graphs
    interference, move_graph = build_graphs(blocks, live_after)

    # 3. Collect variables
    variables = _collect_variables(blocks)

    # 4. Graph coloring (DSATUR + move biasing)
    coloring = color_graph(interference, move_graph, variables)

    # 5. Apply allocation
    new_blocks, num_spills = apply_allocation(blocks, coloring)

    # 6. Patch instructions
    new_blocks = patch_instructions(new_blocks)

    return {
        'blocks': new_blocks,
    }
