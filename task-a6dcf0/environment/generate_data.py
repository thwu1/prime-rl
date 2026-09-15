#!/usr/bin/env python3
"""Generate tree and XOR-encrypted queries for the tree path query engine task."""

import os
import random


def main():
    random.seed(42)
    N = 10000
    Q = 20000

    # Generate tree: node 1 is root, parent[1] = 0 (sentinel)
    parents = [0] * (N + 1)
    edge_weights = [0] * (N + 1)
    for i in range(2, N + 1):
        parents[i] = random.randint(1, i - 1)
        edge_weights[i] = random.randint(1, 100000)

    # Build children list and compute depths via iterative DFS
    children = [[] for _ in range(N + 1)]
    for i in range(2, N + 1):
        children[parents[i]].append(i)

    depth = [0] * (N + 1)
    stack = [1]
    while stack:
        u = stack.pop()
        for v in children[u]:
            depth[v] = depth[u] + 1
            stack.append(v)

    # Binary lifting table for LCA
    LOG = 14  # ceil(log2(10000))
    up = [[0] * (N + 1) for _ in range(LOG)]
    for i in range(1, N + 1):
        up[0][i] = parents[i]
    for k in range(1, LOG):
        for i in range(1, N + 1):
            up[k][i] = up[k - 1][up[k - 1][i]]

    def lca(u, v):
        if depth[u] < depth[v]:
            u, v = v, u
        diff = depth[u] - depth[v]
        for k in range(LOG):
            if (diff >> k) & 1:
                u = up[k][u]
        if u == v:
            return u
        for k in range(LOG - 1, -1, -1):
            if up[k][u] != up[k][v]:
                u = up[k][u]
                v = up[k][v]
        return up[0][u]

    def get_dist(u, v):
        return depth[u] + depth[v] - 2 * depth[lca(u, v)]

    def get_path(u, v):
        l = lca(u, v)
        pu = []
        x = u
        while x != l:
            pu.append(x)
            x = parents[x]
        pu.append(l)
        pv = []
        x = v
        while x != l:
            pv.append(x)
            x = parents[x]
        return pu + pv[::-1]

    # Generate decrypted queries with valid parameters
    qtypes = ['D', 'S', 'M', 'L', 'K', 'U']
    qweights = [5, 5, 5, 5, 3, 7]

    decrypted = []
    for _ in range(Q):
        idx = random.choices(range(6), weights=qweights, k=1)[0]
        qt = qtypes[idx]
        if qt == 'U':
            u = random.randint(2, N)
            w = random.randint(1, 100000)
            decrypted.append(('U', u, w))
        elif qt == 'K':
            u = random.randint(1, N)
            v = random.randint(1, N)
            d = get_dist(u, v)
            k = random.randint(0, d) if d > 0 else 0
            decrypted.append(('K', u, v, k))
        else:
            u = random.randint(1, N)
            v = random.randint(1, N)
            decrypted.append((qt, u, v))

    # Process all decrypted queries to get answers and lastAns sequence
    ew = edge_weights[:]
    answers = []
    last_ans = 0
    la_seq = []

    for q in decrypted:
        la_seq.append(last_ans)
        qt = q[0]
        if qt == 'D':
            ans = get_dist(q[1], q[2])
            answers.append(ans)
            last_ans = ans
        elif qt == 'S':
            l = lca(q[1], q[2])
            s = 0
            x = q[1]
            while x != l:
                s += ew[x]
                x = parents[x]
            x = q[2]
            while x != l:
                s += ew[x]
                x = parents[x]
            answers.append(s)
            last_ans = s
        elif qt == 'M':
            l = lca(q[1], q[2])
            m = 0
            x = q[1]
            while x != l:
                m = max(m, ew[x])
                x = parents[x]
            x = q[2]
            while x != l:
                m = max(m, ew[x])
                x = parents[x]
            answers.append(m)
            last_ans = m
        elif qt == 'L':
            ans = lca(q[1], q[2])
            answers.append(ans)
            last_ans = ans
        elif qt == 'K':
            path = get_path(q[1], q[2])
            ans = path[q[3]]
            answers.append(ans)
            last_ans = ans
        elif qt == 'U':
            ew[q[1]] = q[2]

    # XOR-encrypt queries using lastAns sequence
    encrypted = []
    for i, q in enumerate(decrypted):
        la = la_seq[i]
        qt = q[0]
        if qt == 'U':
            encrypted.append("U {} {}".format(q[1] ^ la, q[2] ^ la))
        elif qt == 'K':
            encrypted.append("K {} {} {}".format(q[1] ^ la, q[2] ^ la, q[3] ^ la))
        else:
            encrypted.append("{} {} {}".format(qt, q[1] ^ la, q[2] ^ la))

    # Write tree file
    os.makedirs('/app', exist_ok=True)
    with open('/app/tree.txt', 'w') as f:
        f.write("{}\n".format(N))
        for i in range(2, N + 1):
            f.write("{} {} {}\n".format(i, parents[i], edge_weights[i]))

    # Write encrypted queries file
    with open('/app/queries.txt', 'w') as f:
        f.write("{}\n".format(Q))
        for q in encrypted:
            f.write(q + "\n")

    # Write small sample for agent testing/development
    os.makedirs('/app/sample', exist_ok=True)
    with open('/app/sample/tree.txt', 'w') as f:
        f.write("3\n")
        f.write("2 1 5\n")
        f.write("3 1 3\n")
    with open('/app/sample/queries.txt', 'w') as f:
        f.write("3\n")
        f.write("D 2 3\n")
        f.write("L 0 1\n")
        f.write("S 3 2\n")
    with open('/app/sample/expected_output.txt', 'w') as f:
        f.write("2\n")
        f.write("1\n")
        f.write("8\n")


if __name__ == '__main__':
    main()
