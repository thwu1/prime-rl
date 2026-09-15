#!/usr/bin/env python3
"""Reference solver for the tree path query engine task."""


def solve():
    # Read tree
    with open('/app/tree.txt') as f:
        N = int(f.readline())
        parents = [0] * (N + 1)
        ew = [0] * (N + 1)
        for _ in range(N - 1):
            parts = f.readline().split()
            node, par, weight = int(parts[0]), int(parts[1]), int(parts[2])
            parents[node] = par
            ew[node] = weight

    # Build children list and compute depths
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

    # Binary lifting for LCA
    LOG = max(1, N.bit_length())
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

    # Read and process encrypted queries
    with open('/app/queries.txt') as f:
        Q = int(f.readline())
        lines = [f.readline().strip() for _ in range(Q)]

    last_ans = 0
    results = []

    for line in lines:
        parts = line.split()
        qt = parts[0]

        if qt == 'U':
            u = int(parts[1]) ^ last_ans
            w = int(parts[2]) ^ last_ans
            ew[u] = w
        elif qt == 'D':
            u = int(parts[1]) ^ last_ans
            v = int(parts[2]) ^ last_ans
            ans = depth[u] + depth[v] - 2 * depth[lca(u, v)]
            results.append(ans)
            last_ans = ans
        elif qt == 'S':
            u = int(parts[1]) ^ last_ans
            v = int(parts[2]) ^ last_ans
            l = lca(u, v)
            s = 0
            x = u
            while x != l:
                s += ew[x]
                x = parents[x]
            x = v
            while x != l:
                s += ew[x]
                x = parents[x]
            results.append(s)
            last_ans = s
        elif qt == 'M':
            u = int(parts[1]) ^ last_ans
            v = int(parts[2]) ^ last_ans
            l = lca(u, v)
            m = 0
            x = u
            while x != l:
                m = max(m, ew[x])
                x = parents[x]
            x = v
            while x != l:
                m = max(m, ew[x])
                x = parents[x]
            results.append(m)
            last_ans = m
        elif qt == 'L':
            u = int(parts[1]) ^ last_ans
            v = int(parts[2]) ^ last_ans
            ans = lca(u, v)
            results.append(ans)
            last_ans = ans
        elif qt == 'K':
            u = int(parts[1]) ^ last_ans
            v = int(parts[2]) ^ last_ans
            k = int(parts[3]) ^ last_ans
            path = get_path(u, v)
            ans = path[k]
            results.append(ans)
            last_ans = ans

    return results


if __name__ == '__main__':
    results = solve()
    with open('/app/results.txt', 'w') as f:
        for r in results:
            f.write("{}\n".format(r))
