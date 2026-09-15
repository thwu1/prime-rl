"""
Register allocator driver. Calls liveness analysis, interference graph
construction, and graph coloring in sequence.
"""
from typing import Dict, Tuple, Optional
from cfg import (CFG, Location, Var, Reg, Deref,
                 ALLOCATABLE_REGS, REG_TO_COLOR, RESERVED_REGS)
from liveness import analyze_liveness
from interference import build_interference
from coloring import dsatur_color


def allocate_registers(cfg: CFG) -> Dict[str, object]:
    """
    Run the full register allocation pipeline on a CFG.

    Returns a dict mapping variable names to their assigned locations:
      - Reg(name) for register-allocated variables
      - Deref('rbp', offset) for spilled variables
    """
    # Step 1: Liveness analysis
    live_after_sets = analyze_liveness(cfg)

    # Step 2: Build interference and move graphs
    interfere_graph, move_graph = build_interference(cfg, live_after_sets)

    # Step 3: Gather all colorable locations
    all_locs = set()
    for block in cfg.blocks.values():
        for instr in block.instrs:
            from cfg import reads_of, writes_of
            all_locs |= reads_of(instr)
            all_locs |= writes_of(instr)
    # Remove reserved registers from coloring
    all_locs = {loc for loc in all_locs if not (isinstance(loc, Reg) and loc.name in RESERVED_REGS)}

    # Pre-assign colors to physical registers
    precolored = {}
    for loc in all_locs:
        if isinstance(loc, Reg) and loc.name in REG_TO_COLOR:
            precolored[loc] = REG_TO_COLOR[loc.name]

    # Step 3: Color the graph
    coloring = dsatur_color(all_locs, interfere_graph, move_graph, precolored)

    # Step 4: Map colors to locations
    num_alloc_regs = len(ALLOCATABLE_REGS)
    result = {}
    spill_count = 0
    for loc, color in coloring.items():
        if isinstance(loc, Var):
            if color < num_alloc_regs:
                result[loc.name] = Reg(ALLOCATABLE_REGS[color])
            else:
                offset = -8 * (color - num_alloc_regs + 1)
                result[loc.name] = Deref('rbp', offset)
                spill_count += 1
        # Physical registers keep their assignment (no entry in result needed)

    return result
