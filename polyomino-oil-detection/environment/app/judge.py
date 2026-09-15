#!/usr/bin/env python3
"""
Interactive judge for the Oil Field Detection problem.
Runs a solver as a subprocess, communicates via stdin/stdout pipes.

Usage: python3 judge.py <instance_file> <solver_command>
Output: JSON with {solved, cost, normalized_cost, ops, N, M, num_oil_cells}
"""

import sys
import json
import math
import random
import subprocess
import os


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python3 judge.py <instance_file> <solver_command>"}))
        sys.exit(1)

    instance_file = sys.argv[1]
    solver_cmd = sys.argv[2]

    with open(instance_file) as f:
        instance = json.load(f)

    N = instance["N"]
    M = instance["M"]
    epsilon = instance["epsilon"]
    polyominoes = [[(c[0], c[1]) for c in p] for p in instance["polyominoes"]]
    placements = instance["placements"]
    seed = instance["seed"]

    rng = random.Random(seed)

    # Build the v(i,j) grid
    grid = [[0] * N for _ in range(N)]
    for k in range(M):
        pr, pc = placements[k]
        for di, dj in polyominoes[k]:
            grid[pr + di][pc + dj] += 1

    # Ground truth: all cells with v > 0
    truth = set()
    for i in range(N):
        for j in range(N):
            if grid[i][j] > 0:
                truth.add((i, j))

    # Launch solver
    env = os.environ.copy()
    proc = subprocess.Popen(
        solver_cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Send problem header
    header_lines = [f"{N} {M} {epsilon}"]
    for k in range(M):
        header_lines.append(str(len(polyominoes[k])))
        for di, dj in polyominoes[k]:
            header_lines.append(f"{di} {dj}")
    header = "\n".join(header_lines) + "\n"

    try:
        proc.stdin.write(header)
        proc.stdin.flush()
    except BrokenPipeError:
        print(json.dumps({"solved": False, "cost": -1, "error": "solver crashed on init"}))
        sys.exit(1)

    cost = 0.0
    max_ops = 2 * N * N
    ops = 0
    solved = False

    while ops < max_ops:
        try:
            line = proc.stdout.readline()
        except Exception:
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0]
        ops += 1

        try:
            if cmd == "d":
                # Drill: exact v(i,j)
                ci, cj = int(parts[1]), int(parts[2])
                if 0 <= ci < N and 0 <= cj < N:
                    proc.stdin.write(f"{grid[ci][cj]}\n")
                else:
                    proc.stdin.write("-1\n")
                proc.stdin.flush()
                cost += 1.0

            elif cmd == "q":
                # Aggregate query: noisy sum
                k = int(parts[1])
                if k < 2:
                    proc.stdin.write("-1\n")
                    proc.stdin.flush()
                    continue
                cells = []
                for idx in range(k):
                    ci = int(parts[2 + 2 * idx])
                    cj = int(parts[3 + 2 * idx])
                    cells.append((ci, cj))
                v_s = sum(grid[ci][cj] for ci, cj in cells)
                mu = (k - v_s) * epsilon + v_s * (1.0 - epsilon)
                sigma = math.sqrt(k * epsilon * (1.0 - epsilon))
                x = rng.gauss(mu, sigma)
                result = max(0, round(x))
                proc.stdin.write(f"{result}\n")
                proc.stdin.flush()
                cost += 1.0 / math.sqrt(k)

            elif cmd == "a":
                # Answer guess
                k = int(parts[1])
                guessed = set()
                for idx in range(k):
                    ci = int(parts[2 + 2 * idx])
                    cj = int(parts[3 + 2 * idx])
                    guessed.add((ci, cj))
                if guessed == truth:
                    try:
                        proc.stdin.write("1\n")
                        proc.stdin.flush()
                    except BrokenPipeError:
                        pass
                    solved = True
                    break
                else:
                    proc.stdin.write("0\n")
                    proc.stdin.flush()
                    cost += 1.0
            else:
                # Unknown command - skip
                pass

        except BrokenPipeError:
            break
        except (ValueError, IndexError):
            # Malformed command
            try:
                proc.stdin.write("-1\n")
                proc.stdin.flush()
            except BrokenPipeError:
                break

    # Cleanup
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait()

    result = {
        "solved": solved,
        "cost": round(cost, 6),
        "normalized_cost": round(cost / (N * N), 6),
        "ops": ops,
        "N": N,
        "M": M,
        "num_oil_cells": len(truth),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
