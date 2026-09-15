#!/usr/bin/env python3
"""
Perft comparison framework: engine vs Stockfish.

Communicates with Stockfish via UCI protocol to obtain reference perft
values, compares against the local engine's divide output, and recursively
drills into discrepancies to isolate the exact positions where the engine
diverges from correct move generation.

Usage:
    python3 perft_compare.py "<fen>" <depth> [max_drill_depth]

Exit code 0 = all results match, 1 = discrepancies found.

"""
import subprocess
import sys
import os


class StockfishUCI:
    """UCI protocol interface to Stockfish for perft queries."""

    def __init__(self, path=None):
        if path is None:
            for candidate in ["/usr/games/stockfish", "/usr/bin/stockfish", "stockfish"]:
                if candidate == "stockfish" or os.path.exists(candidate):
                    path = candidate
                    break
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._read_until("uciok")
        self._send("isready")
        self._read_until("readyok")

    def _send(self, cmd):
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _read_until(self, token):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("Stockfish terminated unexpectedly")
            if token in line:
                return line.strip()

    def perft_divide(self, fen, depth, moves=None):
        """Run 'go perft <depth>' and return (move_counts, total)."""
        pos_cmd = f"position fen {fen}"
        if moves:
            pos_cmd += f" moves {moves}"
        self._send(pos_cmd)
        self._send(f"go perft {depth}")

        results = {}
        while True:
            line = self.proc.stdout.readline().strip()
            if not line:
                continue
            if line.startswith("Nodes searched:"):
                total = int(line.split(":")[1].strip())
                break
            if ": " in line and not line.startswith("info"):
                parts = line.split(": ", 1)
                if len(parts) == 2:
                    move_str = parts[0].strip()
                    try:
                        results[move_str] = int(parts[1].strip())
                    except ValueError:
                        pass
        return results, total

    def close(self):
        try:
            self._send("quit")
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def engine_divide(fen, depth, moves=None):
    """Run the local engine's divide function and return (move_counts, total)."""
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from chess_engine import make_board, divide
    board = make_board(fen, moves or "")
    results = divide(board, depth)
    total = sum(results.values())
    return results, total


def compare_position(sf, fen, depth, moves=None, path_prefix="",
                     max_drill=None, indent=0):
    """Compare engine vs Stockfish at one position; drill into discrepancies."""
    sf_moves, sf_total = sf.perft_divide(fen, depth, moves)
    eng_moves, eng_total = engine_divide(fen, depth, moves)

    all_keys = sorted(set(sf_moves.keys()) | set(eng_moves.keys()))
    discrepancies = []
    pad = "  " * indent

    for mv in all_keys:
        sf_cnt = sf_moves.get(mv, 0)
        eng_cnt = eng_moves.get(mv, 0)
        if sf_cnt != eng_cnt:
            move_path = f"{path_prefix} {mv}".strip() if path_prefix else mv
            diff = eng_cnt - sf_cnt
            sign = "+" if diff > 0 else ""
            print(f"{pad}DIFF {move_path}: engine={eng_cnt} stockfish={sf_cnt} ({sign}{diff})")
            discrepancies.append((move_path, eng_cnt, sf_cnt))

            if depth > 1 and (max_drill is None or indent < max_drill):
                new_moves = f"{moves} {mv}".strip() if moves else mv
                compare_position(
                    sf, fen, depth - 1, new_moves,
                    move_path, max_drill, indent + 1
                )

    if not discrepancies:
        print(f"{pad}depth={depth} total={sf_total} -- all {len(all_keys)} moves match")

    return discrepancies


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} \"<fen>\" <depth> [max_drill]", file=sys.stderr)
        sys.exit(1)

    fen = sys.argv[1]
    depth = int(sys.argv[2])
    max_drill = int(sys.argv[3]) if len(sys.argv) > 3 else depth

    print(f"Comparing engine vs Stockfish")
    print(f"FEN:   {fen}")
    print(f"Depth: {depth}")
    print("---")

    sf = StockfishUCI()
    try:
        discs = compare_position(sf, fen, depth, max_drill=max_drill)
    finally:
        sf.close()

    if discs:
        print(f"\n{len(discs)} top-level move(s) with wrong counts.")
        sys.exit(1)
    else:
        print(f"\nAll results match at depth {depth}.")
        sys.exit(0)


if __name__ == "__main__":
    main()
