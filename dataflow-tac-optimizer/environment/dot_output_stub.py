
"""Graphviz DOT output for CFG visualization.

Generate valid Graphviz DOT notation for control-flow graphs.
Each basic block is a node labeled with its instructions.
Edges represent control-flow between blocks.
"""

from tac_parser import Function, emit_instruction
from cfg import build_cfg


def cfg_to_dot(func: Function) -> str:
    """Generate a Graphviz DOT string for the CFG of the given function.

    Requirements:
    - Graph name must be the function name (quoted)
    - Each reachable basic block is a box-shaped node named B<id>
    - Node labels contain the block's instructions (left-aligned with \\l)
    - Edges connect blocks according to control-flow successors
    - Entry block should have style=bold

    Returns a string containing valid DOT graph notation.
    """
    # TODO: implement
    raise NotImplementedError("CFG to DOT conversion not implemented")
