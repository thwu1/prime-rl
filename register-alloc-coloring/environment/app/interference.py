"""
Interference and move graph construction from liveness information.
"""
from typing import Dict, List, Set, Tuple
from cfg import (CFG, BasicBlock, Instruction, Instr, Callq, Jump, JumpIf,
                 Location, Var, Reg, Immediate, Deref,
                 reads_of, writes_of, CALLER_SAVE_REGS)


# Graph represented as adjacency sets: Dict[Location, Set[Location]]
Graph = Dict[Location, Set[Location]]


def build_interference(cfg: CFG,
                       live_after_sets: Dict[str, List[Set[Location]]]
                       ) -> Tuple[Graph, Graph]:
    """
    Build the interference graph and move graph from the CFG and liveness data.

    Args:
        cfg: The control flow graph.
        live_after_sets: Dict mapping block label to list of live-after sets
                         (one per instruction), as returned by analyze_liveness.

    Returns:
        A tuple (interference_graph, move_graph) where each is a
        Dict[Location, Set[Location]] representing an undirected graph
        via adjacency sets.

    The interference graph captures conflicts between locations: two locations
    that are simultaneously live and therefore cannot share the same physical
    register. The move graph records pairs of locations connected by move
    instructions, which is useful for coloring optimization.

    Important: do NOT include reserved registers (rax, rsp, rbp, r15) in
    either graph. Allocatable physical registers (rbx, rcx, etc.) that
    appear in instructions MUST be included as vertices.
    """
    raise NotImplementedError("Implement build_interference")
