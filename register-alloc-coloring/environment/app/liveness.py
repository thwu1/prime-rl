"""
Liveness analysis for a control flow graph of x86-like instructions.
"""
from typing import Dict, List, Set
from cfg import CFG, BasicBlock, Instruction, Location, reads_of, writes_of, Jump, JumpIf


def analyze_liveness(cfg: CFG) -> Dict[str, List[Set[Location]]]:
    """
    Compute the set of locations live after each instruction in the CFG.

    Args:
        cfg: The control flow graph to analyze.

    Returns:
        A dict mapping each block label to a list of live-after sets.
        For a block with N instructions, the list has N elements where
        element i is the set of locations live AFTER instruction i.

    A location is live after an instruction if it may be read before
    being redefined on some execution path from that point. The
    analysis must produce correct results for CFGs with branches,
    joins, and back-edges (loops).

    For the last instruction of a block, the live-after set depends on
    the block's successors in the control flow graph.
    """
    raise NotImplementedError("Implement analyze_liveness")
