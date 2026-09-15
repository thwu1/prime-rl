"""
Graph coloring for register allocation.
"""
from typing import Dict, Set, Optional
from cfg import Location, Var, Reg

# Graph represented as adjacency sets
Graph = Dict[Location, Set[Location]]


def dsatur_color(vertices: Set[Location],
                 interfere: Graph,
                 moves: Graph,
                 precolored: Dict[Location, int]) -> Dict[Location, int]:
    """
    Assign colors (registers or stack slots) to graph vertices.

    Args:
        vertices: The set of all locations to color.
        interfere: Interference graph (adjacency sets, undirected).
        moves: Move graph (adjacency sets, undirected).
        precolored: Dict mapping pre-colored locations (physical registers)
                    to their fixed colors. These must not be recolored.

    Returns:
        A dict mapping every location in `vertices` to a color (non-negative int).
        Colors 0-11 correspond to allocatable registers (see ALLOCATABLE_REGS
        in cfg.py for the mapping). Colors >= 12 correspond to stack spill
        locations.

    Constraints:
        - No two adjacent vertices in the interference graph share a color.
        - Pre-colored vertices keep their assigned color.
    """
    raise NotImplementedError("Implement dsatur_color")
