#!/usr/bin/env python3
"""Generate text-format optimization instances requiring conversion."""
import os


def gen_ising_chimera():
    """16-spin frustrated graph with mixed ferro/antiferro couplings on a
    4x4 grid augmented with diagonal edges."""
    n = 16
    lines = ["# 16-spin frustrated graph with mixed couplings", f"N {n}"]

    edges = []
    # Horizontal edges in 4x4 grid
    for r in range(4):
        for c in range(3):
            edges.append((r * 4 + c, r * 4 + c + 1))
    # Vertical edges
    for r in range(3):
        for c in range(4):
            edges.append((r * 4 + c, (r + 1) * 4 + c))
    # Diagonal edges (down-right) for frustration
    for r in range(3):
        for c in range(3):
            edges.append((r * 4 + c, (r + 1) * 4 + c + 1))

    for i, j in edges:
        val = round(((i * 23 + j * 37 + 7) % 41) / 20.0 - 1.0, 3)
        lines.append(f"J {i} {j} {val}")

    for i in range(n):
        h = round(((i * 13 + 3) % 17) / 8.0 - 1.0, 3)
        if h != 0.0:
            lines.append(f"H {i} {h}")

    return "\n".join(lines) + "\n"


def gen_qubo_partition():
    """Number partition problem as QUBO with 14 variables.
    Items s_i = ((i*7+3) % 23) + 1. Sum = 164, perfect partition exists."""
    n = 14
    s = [((i * 7 + 3) % 23) + 1 for i in range(n)]
    c = sum(s)

    lines = [
        f"# Number partition QUBO, {n} variables",
        f"# Items: {s}",
        f"# Total sum: {c}",
        f"N {n}",
    ]

    # Diagonal: Q_ii = 4 * s_i * (s_i - c)
    for i in range(n):
        q_ii = 4 * s[i] * (s[i] - c)
        lines.append(f"Q {i} {i} {q_ii:.1f}")

    # Upper triangle: Q_ij = 8 * s_i * s_j for i < j
    for i in range(n):
        for j in range(i + 1, n):
            q_ij = 8 * s[i] * s[j]
            lines.append(f"Q {i} {j} {q_ij:.1f}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raw_dir = "/app/instances/raw"
    os.makedirs(raw_dir, exist_ok=True)

    with open(os.path.join(raw_dir, "ising_chimera.ising"), "w") as f:
        f.write(gen_ising_chimera())
    print(f"Generated {raw_dir}/ising_chimera.ising")

    with open(os.path.join(raw_dir, "qubo_partition.qubo"), "w") as f:
        f.write(gen_qubo_partition())
    print(f"Generated {raw_dir}/qubo_partition.qubo")
