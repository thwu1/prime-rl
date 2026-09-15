"""
NNUE Chess Position Evaluation — Correct Implementation.


This implementation reverse-engineers the /app/nnue_oracle binary, handling three
key discrepancies relative to the spec at /app/spec.md:

1. HORIZONTAL MIRRORING: The spec omits that when the perspective king is on
   files e-h (file index > 3), all feature squares are horizontally mirrored
   (sq ^ 7). This must be discovered by probing the oracle with kings on
   different files and comparing feature outputs.

2. TRUNCATION DIVISION: The spec claims all integer divisions "round toward
   negative infinity" (Python floor division). In reality, the oracle uses
   truncation-toward-zero division (C/Java semantics). For negative dividends:
   Python: -7 // 2 == -4 ; C/Java: -7 / 2 == -3. This must be discovered by
   testing positions that produce negative intermediate values.

3. BUCKET MAP: The spec does not provide the bucket lookup table. It must be
   determined by testing the oracle with kings on each square. The map is:
   ranks 1-2 corner files (a,b,g,h) -> bucket 0
   ranks 1-2 center files (c,d,e,f) -> bucket 1
   ranks 3-5 all files              -> bucket 2
   ranks 6-8 all files              -> bucket 3
"""

import struct

import chess


# ======================== Constants ========================

INPUT_SIZE = 768
HIDDEN_SIZE = 32
NUM_BUCKETS = 4
QA = 255
QB = 64
SCALE = 400

BUCKET_MAP = [
    0, 0, 1, 1, 1, 1, 0, 0,
    0, 0, 1, 1, 1, 1, 0, 0,
    2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2,
    3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3,
]

PHASE_WEIGHT = {
    chess.PAWN: 0,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 10,
    chess.KING: 0,
}

PIECE_TYPE_MAP = {
    chess.PAWN: 0,
    chess.KNIGHT: 1,
    chess.BISHOP: 2,
    chess.ROOK: 3,
    chess.QUEEN: 4,
    chess.KING: 5,
}


# ======================== Truncation Division ========================

def _trunc_div(a, b):
    """Integer division truncating toward zero (C/Java semantics).

    Python's // floors toward negative infinity. C/Java truncate toward zero.
    Difference matters only when signs of a and b differ:
        Python: -7 // 2 == -4
        C/Java: -7 /  2 == -3
    """
    q, r = divmod(a, b)
    if r != 0 and (a < 0) != (b < 0):
        q += 1
    return q


# ======================== Network Loading ========================

def _load_network(path="/app/network.bin"):
    with open(path, "rb") as f:
        data = f.read()

    offset = 0
    n_iw = NUM_BUCKETS * INPUT_SIZE * HIDDEN_SIZE
    iw_flat = struct.unpack_from(f"<{n_iw}h", data, offset)
    offset += n_iw * 2

    input_weights = []
    idx = 0
    for _b in range(NUM_BUCKETS):
        bucket = []
        for _i in range(INPUT_SIZE):
            row = list(iw_flat[idx : idx + HIDDEN_SIZE])
            idx += HIDDEN_SIZE
            bucket.append(row)
        input_weights.append(bucket)

    biases = list(struct.unpack_from(f"<{HIDDEN_SIZE}h", data, offset))
    offset += HIDDEN_SIZE * 2

    output_weights = list(struct.unpack_from(f"<{2 * HIDDEN_SIZE}h", data, offset))
    offset += 2 * HIDDEN_SIZE * 2

    output_bias = struct.unpack_from("<h", data, offset)[0]

    return input_weights, biases, output_weights, output_bias


_INPUT_WEIGHTS, _BIASES, _OUTPUT_WEIGHTS, _OUTPUT_BIAS = _load_network()


# ======================== Feature Computation ========================

def _should_mirror(king_sq):
    """Mirror active when perspective king is on files e-h (file > 3)."""
    return chess.square_file(king_sq) > 3


def _king_bucket(king_sq, is_white):
    """Input bucket for a king square from a given perspective."""
    sq = king_sq if is_white else (king_sq ^ 56)
    return BUCKET_MAP[sq]


def get_features(fen: str, white_perspective: bool) -> list:
    """Return sorted list of active NNUE feature indices for one perspective."""
    board = chess.Board(fen)
    king_sq = board.king(chess.WHITE if white_perspective else chess.BLACK)
    mirror = _should_mirror(king_sq)

    features = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue

        pt = PIECE_TYPE_MAP[piece.piece_type]

        if white_perspective:
            rel_color = 0 if piece.color == chess.WHITE else 1
        else:
            rel_color = 0 if piece.color == chess.BLACK else 1

        adj_sq = sq
        if not white_perspective:
            adj_sq ^= 56
        if mirror:
            adj_sq ^= 7

        feature_idx = rel_color * 384 + pt * 64 + adj_sq
        features.append(feature_idx)

    return sorted(features)


# ======================== Evaluation ========================

def evaluate(fen: str) -> int:
    """Evaluate a chess position. Returns centipawn score for side to move."""
    board = chess.Board(fen)

    white_acc = _init_accumulator(board, True)
    black_acc = _init_accumulator(board, False)

    if board.turn == chess.WHITE:
        us, them = white_acc, black_acc
    else:
        us, them = black_acc, white_acc

    raw_eval = _forward(us, them)

    mp = _material_phase(board)
    raw_eval = _trunc_div(raw_eval * (22400 + mp), 32768)

    hmc = board.halfmove_clock
    raw_eval = _trunc_div(raw_eval * (200 - hmc), 200)

    return raw_eval


# ======================== Internal Helpers ========================

def _init_accumulator(board, white_perspective):
    """Initialise accumulator from biases + weighted active features."""
    king_sq = board.king(chess.WHITE if white_perspective else chess.BLACK)
    bucket = _king_bucket(king_sq, white_perspective)

    acc = list(_BIASES)
    features = get_features(board.fen(), white_perspective)

    for f_idx in features:
        for h in range(HIDDEN_SIZE):
            acc[h] += _INPUT_WEIGHTS[bucket][f_idx][h]

    return acc


def _activation(x):
    """SCReLU: clamp to [0, QA] then square."""
    clamped = max(0, min(x, QA))
    return clamped * clamped


def _forward(us_acc, them_acc):
    """Quantised forward pass (truncation division matching C/Java semantics)."""
    output = 0
    for h in range(HIDDEN_SIZE):
        output += _activation(us_acc[h]) * _OUTPUT_WEIGHTS[h]
        output += _activation(them_acc[h]) * _OUTPUT_WEIGHTS[HIDDEN_SIZE + h]

    return _trunc_div((_trunc_div(output, QA) + _OUTPUT_BIAS) * SCALE, QA * QB)


def _material_phase(board):
    """Weighted piece count for phase scaling."""
    phase = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is not None:
            phase += PHASE_WEIGHT[piece.piece_type]
    return phase
