#!/usr/bin/env python3
"""
Python ctypes bridge for libperft960.so

Loads the Chess960 perft shared library and exposes a run_perft() function
that maps C struct layouts to Python and returns extended perft statistics.
"""


import ctypes
import os


_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libperft960.so')
_lib = ctypes.CDLL(_lib_path)


class Board(ctypes.Structure):
    """Maps the C Board struct layout for ctypes interop."""
    _fields_ = [
        ("sq", ctypes.c_int * 64),
        ("side", ctypes.c_int),
        ("castle", ctypes.c_int),
        ("ep", ctypes.c_int),
        ("king_sq", ctypes.c_int * 2),
        ("castle_rook", ctypes.c_int * 4),
    ]


class Stats(ctypes.Structure):
    """Maps the C Stats struct layout for ctypes interop."""
    _fields_ = [
        ("nodes", ctypes.c_longlong),
        ("captures", ctypes.c_longlong),
        ("ep", ctypes.c_longlong),
        ("castles", ctypes.c_longlong),
        ("promotions", ctypes.c_longlong),
        ("checks", ctypes.c_longlong),
        ("checkmates", ctypes.c_longlong),
    ]


# Declare C function signatures
_lib.parse_fen.argtypes = [ctypes.POINTER(Board), ctypes.c_char_p]
_lib.parse_fen.restype = None

_lib.perft.argtypes = [ctypes.POINTER(Board), ctypes.c_int, ctypes.POINTER(Stats)]
_lib.perft.restype = None


def run_perft(fen: str, depth: int) -> dict:
    """
    Run perft on the given FEN at the specified depth via the C shared library.

    Returns a dict with keys: nodes, captures, ep, castles, promotions, checks, checkmates
    """
    board = Board()
    stats = Stats()
    _lib.parse_fen(ctypes.byref(board), fen.encode('utf-8'))
    _lib.perft(ctypes.byref(board), depth, ctypes.byref(stats))
    return {
        "nodes": stats.nodes,
        "captures": stats.captures,
        "ep": stats.ep,
        "castles": stats.castles,
        "promotions": stats.promotions,
        "checks": stats.checks,
        "checkmates": stats.checkmates,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} \"FEN\" depth")
        sys.exit(1)
    result = run_perft(sys.argv[1], int(sys.argv[2]))
    for k, v in result.items():
        print(f"{k}: {v}")
