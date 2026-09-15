"""
NNUE Chess Position Evaluator.

Reverse-engineer the behavior of /app/nnue_oracle and implement a matching
evaluator in Python. The network weights are at /app/network.bin and a partial
specification is at /app/spec.md.

Required interface:
    evaluate(fen: str) -> int
    get_features(fen: str, white_perspective: bool) -> list[int]
"""


def evaluate(fen: str) -> int:
    """Evaluate a chess position given as a FEN string.
    Returns integer centipawn score from the side-to-move's perspective.
    """
    raise NotImplementedError


def get_features(fen: str, white_perspective: bool) -> list[int]:
    """Get sorted list of active input feature indices for the given perspective.
    Each index is in [0, 767].
    """
    raise NotImplementedError
