"""Sea of Nodes IR framework inspired by the Tilde Backend (TB)."""

from .nodes import Node, NodeType, DataType, I1, I8, I16, I32, I64, reset_node_ids
from .graph import Graph
from .evaluator import evaluate
