"""Complete register allocator: liveness analysis + interference graph + DSATUR.

"""
from ir import CFG, Block, Instr, VReg, PReg, Imm, Deref
from x86_defs import (
    CALLER_SAVED_SET,
    REG_TO_COLOR, COLOR_TO_REG, NUM_REGS,
    locations_read, locations_written, is_move_instr, successor_labels,
)
from graph import UndirectedGraph


# -----------------------------------------------------------------------
# 1. Liveness analysis  (iterative backward dataflow)
# -----------------------------------------------------------------------

def compute_liveness(cfg: CFG):
    """Return *live_after*: ``(block_label, instr_index) -> frozenset``."""

    # --- block-level use / def (use-before-def) -------------------------
    block_use = {}
    block_def = {}
    for label, block in cfg.blocks.items():
        use, defn = set(), set()
        for instr in block.instrs:
            for loc in locations_read(instr):
                if loc not in defn:
                    use.add(loc)
            defn.update(locations_written(instr))
        block_use[label] = use
        block_def[label] = defn

    # --- fixed-point iteration ------------------------------------------
    live_in  = {label: set() for label in cfg.blocks}
    live_out = {label: set() for label in cfg.blocks}

    changed = True
    while changed:
        changed = False
        for label, block in cfg.blocks.items():
            new_out = set()
            for succ in successor_labels(block):
                new_out |= live_in[succ]
            new_in = (new_out - block_def[label]) | block_use[label]
            if new_in != live_in[label] or new_out != live_out[label]:
                changed = True
                live_in[label]  = new_in
                live_out[label] = new_out

    # --- per-instruction live_after -------------------------------------
    result = {}
    for label, block in cfg.blocks.items():
        instrs = block.instrs
        n = len(instrs)
        if n == 0:
            continue
        current = set(live_out[label])
        for i in range(n - 1, -1, -1):
            result[(label, i)] = frozenset(current)
            instr = instrs[i]
            current = (current - locations_written(instr)) | locations_read(instr)

    return result


# -----------------------------------------------------------------------
# 2. Interference graph
# -----------------------------------------------------------------------

def build_interference(cfg: CFG, live_after):
    """Build an undirected interference graph over VReg/PReg vertices."""
    graph = UndirectedGraph()

    # ensure every mentioned location is a vertex
    for label, block in cfg.blocks.items():
        for i, instr in enumerate(block.instrs):
            for loc in locations_read(instr) | locations_written(instr):
                if isinstance(loc, (VReg, PReg)):
                    graph.add_vertex(loc)
            for loc in live_after.get((label, i), frozenset()):
                if isinstance(loc, (VReg, PReg)):
                    graph.add_vertex(loc)

    # add interference edges
    for label, block in cfg.blocks.items():
        for i, instr in enumerate(block.instrs):
            la = live_after.get((label, i), frozenset())
            written = locations_written(instr)

            if is_move_instr(instr):
                src = instr.args[0]
                for d in written:
                    for v in la:
                        if v != d and v != src:
                            graph.add_edge(d, v)
            else:
                for d in written:
                    for v in la:
                        if v != d:
                            graph.add_edge(d, v)

    return graph


# -----------------------------------------------------------------------
# 3. Move graph  (for move biasing in DSATUR)
# -----------------------------------------------------------------------

def build_move_graph(cfg: CFG):
    graph = UndirectedGraph()
    for block in cfg.blocks.values():
        for instr in block.instrs:
            if is_move_instr(instr):
                src, dst = instr.args[0], instr.args[1]
                graph.add_vertex(src)
                graph.add_vertex(dst)
                graph.add_edge(src, dst)
    return graph


# -----------------------------------------------------------------------
# 4. DSATUR colouring
# -----------------------------------------------------------------------

def dsatur_color(interference, move_graph, precolored):
    """Colour *interference* using DSATUR.  Return ``vertex -> colour``."""
    coloring = dict(precolored)
    uncolored = {v for v in interference.vertices() if v not in coloring}

    def saturation(v):
        return len({coloring[u] for u in interference.adjacent(v) if u in coloring})

    while uncolored:
        v = max(uncolored, key=lambda v: (saturation(v), interference.degree(v)))

        used = {coloring[u] for u in interference.adjacent(v) if u in coloring}

        # move biasing: prefer a colour shared with a move-related neighbour
        preferred = None
        if v in move_graph:
            for u in move_graph.adjacent(v):
                if u in coloring and coloring[u] not in used:
                    preferred = coloring[u]
                    break

        if preferred is not None:
            color = preferred
        else:
            color = 0
            while color in used:
                color += 1

        coloring[v] = color
        uncolored.remove(v)

    return coloring


# -----------------------------------------------------------------------
# 5. Main entry point
# -----------------------------------------------------------------------

def allocate_registers(cfg: CFG) -> CFG:
    live_after   = compute_liveness(cfg)
    interference = build_interference(cfg, live_after)
    move_graph   = build_move_graph(cfg)

    # pre-colour physical registers
    precolored = {}
    for v in interference.vertices():
        if isinstance(v, PReg) and v in REG_TO_COLOR:
            precolored[v] = REG_TO_COLOR[v]

    coloring = dsatur_color(interference, move_graph, precolored)

    # colour -> physical location
    color_map = {}
    for c in set(coloring.values()):
        if c < NUM_REGS:
            color_map[c] = COLOR_TO_REG[c]
        else:
            color_map[c] = Deref('rbp', -(c - NUM_REGS + 1) * 8)

    # rewrite CFG
    def rewrite(op):
        if isinstance(op, VReg):
            return color_map[coloring[op]]
        return op          # PReg, Imm, Deref, str — unchanged

    new_blocks = {}
    for label, block in cfg.blocks.items():
        new_instrs = []
        for instr in block.instrs:
            new_args = [rewrite(a) if not isinstance(a, str) else a
                        for a in instr.args]
            new_instrs.append(Instr(instr.op, new_args))
        new_blocks[label] = Block(label, new_instrs)

    return CFG(blocks=new_blocks, entry=cfg.entry)
