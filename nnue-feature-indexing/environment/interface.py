"""
NNUE feature computation interface.
Implement all functions in /app/nnue_features.py.

Square numbering follows LERF convention
(a1=0, b1=1, ..., h1=7, a2=8, ..., h8=63).
"""


def parse_fen(fen: str):
    """Parse a FEN string into a position representation."""
    raise NotImplementedError


def active_features(pos, white_perspective: bool) -> tuple:
    """Return (bucket_index, sorted_feature_list) for a position and perspective."""
    raise NotImplementedError


def make_move(pos, uci_move: str):
    """Apply a UCI move (e.g. 'e2e4', 'e1g1', 'e7e8q') and return a new position.
    Must not mutate the original."""
    raise NotImplementedError


def needs_refresh(pos, uci_move: str, white_perspective: bool) -> bool:
    """Whether a full accumulator refresh is needed for this perspective."""
    raise NotImplementedError


def feature_delta(pos, uci_move: str, white_perspective: bool) -> tuple:
    """Return (sorted_adds, sorted_subs) for an incremental update.
    Only valid when needs_refresh returns False for the same perspective."""
    raise NotImplementedError


def feature_index(piece_type: int, piece_white: bool, sq: int,
                  white_perspective: bool, king_sq: int) -> int:
    """Compute a single NNUE feature index (0-767)."""
    raise NotImplementedError


def king_bucket(king_sq: int, white_perspective: bool) -> int:
    """Compute the input bucket for a king position."""
    raise NotImplementedError
