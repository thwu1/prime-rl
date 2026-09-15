#!/usr/bin/env python3

"""
Solve the chess puzzle theme classifier by implementing all detection functions.
Each detector requires chess domain expertise to correctly identify tactical patterns
in puzzle solution lines using the python-chess library and the provided utility module.
"""


from typing import List, Optional
import chess
from chess import (
    square_rank,
    square_file,
    Board,
    SquareSet,
    Piece,
    PieceType,
    square_distance,
)
from chess import KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN
from chess import WHITE, BLACK
from chess.pgn import ChildNode
from model import Puzzle
import util
from util import material_diff


def fork(puzzle: Puzzle) -> bool:
    for node in puzzle.mainline[1::2][:-1]:
        if util.moved_piece_type(node) is not KING:
            board = node.board()
            if util.is_in_bad_spot(board, node.move.to_square):
                continue
            nb = 0
            for piece, square in util.attacked_opponent_squares(
                board, node.move.to_square, puzzle.pov
            ):
                if piece.piece_type == PAWN:
                    continue
                if util.king_values[piece.piece_type] > util.king_values[
                    util.moved_piece_type(node)
                ] or (
                    util.is_hanging(board, piece, square)
                    and square
                    not in board.attackers(not puzzle.pov, node.move.to_square)
                ):
                    nb += 1
            if nb > 1:
                return True
    return False


def skewer(puzzle: Puzzle) -> bool:
    for node in puzzle.mainline[1::2][1:]:
        prev = node.parent
        assert isinstance(prev, ChildNode)
        capture = prev.board().piece_at(node.move.to_square)
        if (
            capture
            and util.moved_piece_type(node) in util.ray_piece_types
            and not node.board().is_checkmate()
        ):
            between = SquareSet.between(node.move.from_square, node.move.to_square)
            op_move = prev.move
            assert op_move
            if (
                op_move.to_square == node.move.to_square
                or not op_move.from_square in between
            ):
                continue
            if util.king_values[util.moved_piece_type(prev)] > util.king_values[
                capture.piece_type
            ] and util.is_in_bad_spot(prev.board(), node.move.to_square):
                return True
    return False


def discovered_attack(puzzle: Puzzle) -> bool:
    for node in puzzle.mainline[1::2]:
        board = node.board()
        checkers = board.checkers()
        if checkers and not node.move.to_square in checkers:
            return True

    for node in puzzle.mainline[1::2][1:]:
        if util.is_capture(node):
            between = SquareSet.between(node.move.from_square, node.move.to_square)
            assert isinstance(node.parent, ChildNode)
            if node.parent.move.to_square == node.move.to_square:
                return False
            prev = node.parent.parent
            assert isinstance(prev, ChildNode)
            if (
                prev.move.from_square in between
                and node.move.to_square != prev.move.to_square
                and node.move.from_square != prev.move.to_square
                and not util.is_castling(prev)
            ):
                return True
    return False


def pin_prevents_attack(puzzle: Puzzle) -> bool:
    for node in puzzle.mainline[1::2]:
        board = node.board()
        for square, piece in board.piece_map().items():
            if piece.color == puzzle.pov:
                continue
            pin_dir = board.pin(piece.color, square)
            if pin_dir == chess.BB_ALL:
                continue
            for attack in board.attacks(square):
                attacked = board.piece_at(attack)
                if (
                    attacked
                    and attacked.color == puzzle.pov
                    and not attack in pin_dir
                    and (
                        util.values[attacked.piece_type]
                        > util.values[piece.piece_type]
                        or util.is_hanging(board, attacked, attack)
                    )
                ):
                    return True
    return False


def pin_prevents_escape(puzzle: Puzzle) -> bool:
    for node in puzzle.mainline[1::2]:
        board = node.board()
        for pinned_square, pinned_piece in board.piece_map().items():
            if pinned_piece.color == puzzle.pov:
                continue
            pin_dir = board.pin(pinned_piece.color, pinned_square)
            if pin_dir == chess.BB_ALL:
                continue
            for attacker_square in board.attackers(puzzle.pov, pinned_square):
                if attacker_square in pin_dir:
                    attacker = board.piece_at(attacker_square)
                    assert attacker
                    if (
                        util.values[pinned_piece.piece_type]
                        > util.values[attacker.piece_type]
                    ):
                        return True
                    if (
                        util.is_hanging(board, pinned_piece, pinned_square)
                        and pinned_square
                        not in board.attackers(not puzzle.pov, attacker_square)
                        and [
                            m
                            for m in board.pseudo_legal_moves
                            if m.from_square == pinned_square
                            and m.to_square not in pin_dir
                        ]
                    ):
                        return True
    return False


def back_rank_mate(puzzle: Puzzle) -> bool:
    node = puzzle.game.end()
    board = node.board()
    king = board.king(not puzzle.pov)
    assert king is not None
    assert isinstance(node, ChildNode)
    back_rank = 7 if puzzle.pov else 0
    if board.is_checkmate() and square_rank(king) == back_rank:
        squares = SquareSet.from_square(king + (-8 if puzzle.pov else 8))
        if puzzle.pov:
            if chess.square_file(king) < 7:
                squares.add(king - 7)
            if chess.square_file(king) > 0:
                squares.add(king - 9)
        else:
            if chess.square_file(king) < 7:
                squares.add(king + 9)
            if chess.square_file(king) > 0:
                squares.add(king + 7)
        for square in squares:
            piece = board.piece_at(square)
            if (
                piece is None
                or piece.color == puzzle.pov
                or board.attackers(puzzle.pov, square)
            ):
                return False
        return any(
            square_rank(checker) == back_rank for checker in board.checkers()
        )
    return False


def smothered_mate(puzzle: Puzzle) -> bool:
    board = puzzle.game.end().board()
    king_square = board.king(not puzzle.pov)
    assert king_square is not None
    if not board.is_checkmate():
        return False
    for checker_square in board.checkers():
        piece = board.piece_at(checker_square)
        assert piece
        if piece.piece_type == KNIGHT:
            for escape_square in [
                s
                for s in chess.SQUARES
                if square_distance(s, king_square) == 1
            ]:
                blocker = board.piece_at(escape_square)
                if not blocker or blocker.color == puzzle.pov:
                    return False
            return True
    return False


def trapped_piece(puzzle: Puzzle) -> bool:
    for node in puzzle.mainline[1::2][1:]:
        square = node.move.to_square
        captured = node.parent.board().piece_at(square)
        if captured and captured.piece_type != PAWN:
            prev = node.parent
            assert isinstance(prev, ChildNode)
            if prev.move.to_square == square:
                square = prev.move.from_square
            if util.is_trapped(prev.parent.board(), square):
                return True
    return False
'''

# Write the solution to /app/tagger.py
with open('/app/tagger.py', 'w') as f:
    f.write(TAGGER_SOURCE)

# Verify the solution loads correctly
import sys
sys.path.insert(0, '/app')
from importlib import invalidate_caches
invalidate_caches()

import importlib
if 'tagger' in sys.modules:
    del sys.modules['tagger']

import tagger

detectors = [
    'fork', 'skewer', 'discovered_attack',
    'pin_prevents_attack', 'pin_prevents_escape',
    'back_rank_mate', 'smothered_mate', 'trapped_piece'
]

for name in detectors:
    func = getattr(tagger, name, None)
    assert func is not None, f"Missing detector: {name}"
    assert callable(func), f"Not callable: {name}"

print(f"All {len(detectors)} detectors implemented and verified as callable.")
