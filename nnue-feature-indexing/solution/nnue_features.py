
"""NNUE feature index computation module — reference implementation."""

# ─── Constants ────────────────────────────────────────────────────────────

INPUT_BUCKETS = [
    0, 1, 2, 3, 3, 2, 1, 0,
    4, 4, 5, 5, 5, 5, 4, 4,
    6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6,
    7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7,
]

PIECE_TYPE_FROM_CHAR = {
    'P': 0, 'N': 1, 'B': 2, 'R': 3, 'Q': 4, 'K': 5,
    'p': 0, 'n': 1, 'b': 2, 'r': 3, 'q': 4, 'k': 5,
}
PROMO_MAP = {'q': 4, 'r': 3, 'b': 2, 'n': 1}
PIECE_CHARS_WHITE = 'PNBRQK'
PIECE_CHARS_BLACK = 'pnbrqk'


# ─── Helpers ──────────────────────────────────────────────────────────────

def flip_rank(sq):
    return sq ^ 56

def flip_file(sq):
    return sq ^ 7

def file_of(sq):
    return sq & 7

def rank_of(sq):
    return sq >> 3

def _sq_from_algebraic(s):
    return (int(s[1]) - 1) * 8 + (ord(s[0]) - ord('a'))

def _sq_to_algebraic(sq):
    return chr(ord('a') + file_of(sq)) + str(rank_of(sq) + 1)


# ─── Position ─────────────────────────────────────────────────────────────

class Position:
    __slots__ = ('pieces', 'white_to_move', 'castling', 'ep_square',
                 'halfmove', 'fullmove')

    def __init__(self):
        self.pieces = {}            # sq -> (piece_type: int, is_white: bool)
        self.white_to_move = True
        self.castling = {'K': False, 'Q': False, 'k': False, 'q': False}
        self.ep_square = None
        self.halfmove = 0
        self.fullmove = 1

    def copy(self):
        p = Position()
        p.pieces = dict(self.pieces)
        p.white_to_move = self.white_to_move
        p.castling = dict(self.castling)
        p.ep_square = self.ep_square
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p

    def king_square(self, white):
        for sq, (pt, pw) in self.pieces.items():
            if pt == 5 and pw == white:
                return sq
        return None


# ─── FEN parsing ──────────────────────────────────────────────────────────

def parse_fen(fen):
    pos = Position()
    parts = fen.split()
    board_str = parts[0]

    ranks = board_str.split('/')
    for rank_idx, rank in enumerate(reversed(ranks)):
        file_idx = 0
        for ch in rank:
            if ch.isdigit():
                file_idx += int(ch)
            else:
                sq = rank_idx * 8 + file_idx
                pos.pieces[sq] = (PIECE_TYPE_FROM_CHAR[ch], ch.isupper())
                file_idx += 1

    pos.white_to_move = (parts[1] == 'w')

    castling_str = parts[2]
    for c in 'KQkq':
        pos.castling[c] = c in castling_str

    if parts[3] != '-':
        pos.ep_square = _sq_from_algebraic(parts[3])

    if len(parts) > 4:
        pos.halfmove = int(parts[4])
    if len(parts) > 5:
        pos.fullmove = int(parts[5])

    return pos


# ─── Core feature computation ────────────────────────────────────────────

def king_bucket(king_sq, white_perspective):
    adj = king_sq if white_perspective else flip_rank(king_sq)
    return INPUT_BUCKETS[adj]


def _should_mirror(king_adj):
    return file_of(king_adj) > 3


def feature_index(piece_type, piece_white, sq, white_perspective, king_sq):
    mapped = sq if white_perspective else flip_rank(sq)
    king_adj = king_sq if white_perspective else flip_rank(king_sq)
    if _should_mirror(king_adj):
        mapped = flip_file(mapped)
    color_offset = 0 if (piece_white == white_perspective) else 1
    return color_offset * 384 + piece_type * 64 + mapped


def active_features(pos, white_perspective):
    ksq = pos.king_square(white_perspective)
    bucket = king_bucket(ksq, white_perspective)
    features = []
    for sq, (pt, pw) in pos.pieces.items():
        features.append(feature_index(pt, pw, sq, white_perspective, ksq))
    return bucket, sorted(features)


# ─── Move detection helpers ───────────────────────────────────────────────

def _is_castling(pos, from_sq, to_sq):
    if from_sq not in pos.pieces:
        return False
    pt, _ = pos.pieces[from_sq]
    return pt == 5 and abs(file_of(from_sq) - file_of(to_sq)) > 1


def _castling_dest(from_sq, to_sq):
    """Return (king_to, rook_from, rook_to) for a castling move."""
    rank = rank_of(from_sq)
    if file_of(to_sq) > file_of(from_sq):          # kingside
        return rank * 8 + 6, rank * 8 + 7, rank * 8 + 5
    else:                                            # queenside
        return rank * 8 + 2, rank * 8 + 0, rank * 8 + 3


# ─── Refresh detection ───────────────────────────────────────────────────

def needs_refresh(pos, uci_move, white_perspective):
    from_sq = _sq_from_algebraic(uci_move[0:2])
    to_sq = _sq_from_algebraic(uci_move[2:4])

    if from_sq not in pos.pieces:
        return False
    pt, pw = pos.pieces[from_sq]
    if pt != 5 or pw != white_perspective:
        return False

    if _is_castling(pos, from_sq, to_sq):
        dest_ksq, _, _ = _castling_dest(from_sq, to_sq)
    else:
        dest_ksq = to_sq

    old_adj = from_sq if white_perspective else flip_rank(from_sq)
    new_adj = dest_ksq if white_perspective else flip_rank(dest_ksq)

    return (INPUT_BUCKETS[old_adj] != INPUT_BUCKETS[new_adj] or
            _should_mirror(old_adj) != _should_mirror(new_adj))


# ─── Feature delta ────────────────────────────────────────────────────────

def feature_delta(pos, uci_move, white_perspective):
    from_sq = _sq_from_algebraic(uci_move[0:2])
    to_sq = _sq_from_algebraic(uci_move[2:4])
    promo = uci_move[4] if len(uci_move) > 4 else None

    pt, pw = pos.pieces[from_sq]
    captured = pos.pieces.get(to_sq)
    ksq = pos.king_square(white_perspective)

    adds = []
    subs = []

    is_castle = _is_castling(pos, from_sq, to_sq)
    is_ep = (pt == 0 and pos.ep_square is not None and to_sq == pos.ep_square)

    if is_castle:
        king_to, rook_from, rook_to = _castling_dest(from_sq, to_sq)
        subs.append(feature_index(5, pw, from_sq, white_perspective, ksq))
        adds.append(feature_index(5, pw, king_to, white_perspective, ksq))
        subs.append(feature_index(3, pw, rook_from, white_perspective, ksq))
        adds.append(feature_index(3, pw, rook_to, white_perspective, ksq))

    elif is_ep:
        cap_sq = to_sq + (-8 if pos.white_to_move else 8)
        subs.append(feature_index(0, pw, from_sq, white_perspective, ksq))
        adds.append(feature_index(0, pw, to_sq, white_perspective, ksq))
        subs.append(feature_index(0, not pw, cap_sq, white_perspective, ksq))

    else:
        new_pt = PROMO_MAP[promo.lower()] if promo else pt
        subs.append(feature_index(pt, pw, from_sq, white_perspective, ksq))
        adds.append(feature_index(new_pt, pw, to_sq, white_perspective, ksq))
        if captured:
            subs.append(feature_index(captured[0], captured[1], to_sq,
                                      white_perspective, ksq))

    return sorted(adds), sorted(subs)


# ─── Move application ────────────────────────────────────────────────────

def make_move(pos, uci_move):
    new = pos.copy()
    from_sq = _sq_from_algebraic(uci_move[0:2])
    to_sq = _sq_from_algebraic(uci_move[2:4])
    promo = uci_move[4] if len(uci_move) > 4 else None

    pt, pw = new.pieces[from_sq]
    captured = new.pieces.get(to_sq)
    is_castle = _is_castling(new, from_sq, to_sq)
    is_ep = (pt == 0 and new.ep_square is not None and to_sq == new.ep_square)

    del new.pieces[from_sq]

    if is_castle:
        king_to, rook_from, rook_to = _castling_dest(from_sq, to_sq)
        new.pieces[king_to] = (5, pw)
        if rook_from in new.pieces:
            del new.pieces[rook_from]
        new.pieces[rook_to] = (3, pw)

    elif is_ep:
        cap_sq = to_sq + (-8 if new.white_to_move else 8)
        if cap_sq in new.pieces:
            del new.pieces[cap_sq]
        new.pieces[to_sq] = (0, pw)

    elif promo:
        new.pieces[to_sq] = (PROMO_MAP[promo.lower()], pw)

    else:
        new.pieces[to_sq] = (pt, pw)

    # Update castling rights
    if pt == 5:
        if pw:
            new.castling['K'] = False
            new.castling['Q'] = False
        else:
            new.castling['k'] = False
            new.castling['q'] = False
    if pt == 3:
        if from_sq == 0:  new.castling['Q'] = False
        elif from_sq == 7:  new.castling['K'] = False
        elif from_sq == 56: new.castling['q'] = False
        elif from_sq == 63: new.castling['k'] = False
    # Rook captured
    if to_sq == 0:  new.castling['Q'] = False
    elif to_sq == 7:  new.castling['K'] = False
    elif to_sq == 56: new.castling['q'] = False
    elif to_sq == 63: new.castling['k'] = False

    # EP square
    new.ep_square = None
    if pt == 0 and abs(rank_of(to_sq) - rank_of(from_sq)) == 2:
        new.ep_square = (from_sq + to_sq) // 2

    # Clocks
    if pt == 0 or captured is not None or is_ep:
        new.halfmove = 0
    else:
        new.halfmove += 1

    if not new.white_to_move:
        new.fullmove += 1

    new.white_to_move = not new.white_to_move
    return new
