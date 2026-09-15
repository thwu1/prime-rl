#!/usr/bin/env python3
"""
Compatible reimplementation of the graphtool reference binary.

"""

import sys
import heapq
import bisect
import struct
import zlib


class Graph:
    def __init__(self):
        self.weighted = False
        self.nodes = set()
        self.adj = {}
        self.seen = {}

    def add_node(self, name):
        self.nodes.add(name)
        if name not in self.adj:
            self.adj[name] = []

    def add_edge(self, src, dst, w):
        self.add_node(src)
        self.add_node(dst)
        if src not in self.seen:
            self.seen[src] = set()
        if dst in self.seen[src]:
            return
        self.seen[src].add(dst)
        self.adj[src].append((dst, w))


def is_valid_ident(s):
    if not s:
        return False
    if not (s[0].isalpha() or s[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in s)


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_graph(path):
    g = Graph()
    try:
        f = open(path)
    except (FileNotFoundError, IOError):
        die(f"cannot open file: {path}")
    with f:
        for ln, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line == "@weighted":
                g.weighted = True
                continue
            if line.startswith("node "):
                name = line[5:].strip()
                if not is_valid_ident(name):
                    die(f"line {ln}: invalid node name '{name}'")
                g.add_node(name)
                continue
            if line.startswith("edge "):
                rest = line[5:]
                arr = rest.find("->")
                if arr == -1:
                    die(f"line {ln}: missing '->' in edge")
                src = rest[:arr].strip()
                after = rest[arr + 2 :].strip()
                tokens = after.split()
                if not tokens:
                    die(f"line {ln}: missing destination")
                dst = tokens[0]
                if not is_valid_ident(src) or not is_valid_ident(dst):
                    die(f"line {ln}: invalid node name")
                w = 1.0
                if g.weighted and len(tokens) > 1:
                    try:
                        w = float(tokens[1])
                    except ValueError:
                        die(f"line {ln}: invalid weight '{tokens[1]}'")
                    if w < 0:
                        die(f"line {ln}: weight must be non-negative")
                g.add_edge(src, dst, w)
                continue
            die(f"line {ln}: unrecognized: {line}")
    return g


def cmd_info(g):
    n = len(g.nodes)
    e = sum(len(es) for es in g.adj.values())
    d = e / (n * (n - 1)) if n > 1 else 0.0
    sl = sum(1 for src in g.adj for dst, _ in g.adj[src] if dst == src)
    print(f"nodes: {n}")
    print(f"edges: {e}")
    print(f"weighted: {'true' if g.weighted else 'false'}")
    print(f"density: {d:.4f}")
    print(f"self_loops: {sl}")


def cmd_adj(g):
    for node in sorted(g.nodes):
        edges = sorted(g.adj[node], key=lambda e: e[0])
        if not edges:
            print(f"{node} -> (none)")
        else:
            if g.weighted:
                parts = [f"{dst}({w:.1f})" for dst, w in edges]
            else:
                parts = [dst for dst, _ in edges]
            print(f"{node} -> {', '.join(parts)}")


def cmd_shortest(g, src, dst):
    if src not in g.nodes:
        die(f"node '{src}' not found")
    if dst not in g.nodes:
        die(f"node '{dst}' not found")
    if src == dst:
        print(src)
        print("distance: 0")
        if g.weighted:
            print("cost: 0.0")
        return
    if g.weighted:
        _dijkstra(g, src, dst)
    else:
        _bfs(g, src, dst)


def _dijkstra(g, src, dst):
    best = {}
    counter = 0
    h = [(0.0, 0, src, counter, [src])]
    counter += 1
    while h:
        cost, dist, node, _, path = heapq.heappop(h)
        if node == dst:
            print(" -> ".join(path))
            print(f"distance: {dist}")
            print(f"cost: {cost:.1f}")
            return
        if node in best and best[node] <= cost:
            continue
        best[node] = cost
        for nbr, w in g.adj.get(node, []):
            nc = cost + w
            if nbr in best and best[nbr] <= nc:
                continue
            heapq.heappush(h, (nc, dist + 1, nbr, counter, path + [nbr]))
            counter += 1
    print(f"no path from {src} to {dst}")


def _bfs(g, src, dst):
    vis = {src}
    queue = [(src, [src])]
    while queue:
        node, path = queue.pop(0)
        if node == dst:
            print(" -> ".join(path))
            print(f"distance: {len(path) - 1}")
            return
        for nbr, _ in sorted(g.adj.get(node, []), key=lambda e: e[0]):
            if nbr not in vis:
                vis.add(nbr)
                queue.append((nbr, path + [nbr]))
    print(f"no path from {src} to {dst}")


def cmd_topo(g):
    indeg = {n: 0 for n in g.nodes}
    for es in g.adj.values():
        for dst, _ in es:
            indeg[dst] += 1
    avail = sorted(n for n, d in indeg.items() if d == 0)
    result = []
    while avail:
        node = avail.pop(0)
        result.append(node)
        for nbr, _ in g.adj.get(node, []):
            indeg[nbr] -= 1
            if indeg[nbr] == 0:
                bisect.insort(avail, nbr)
    if len(result) != len(g.nodes):
        die("graph contains a cycle")
    for n in result:
        print(n)


def cmd_allpaths(g, src, dst):
    if src not in g.nodes:
        die(f"node '{src}' not found")
    if dst not in g.nodes:
        die(f"node '{dst}' not found")

    results = []
    vis = {src}

    def dfs(node, path, cost):
        if node == dst:
            results.append((list(path), cost, len(path) - 1))
            return
        for nbr, w in g.adj.get(node, []):
            if nbr not in vis:
                vis.add(nbr)
                path.append(nbr)
                dfs(nbr, path, cost + w)
                path.pop()
                vis.discard(nbr)

    dfs(src, [src], 0.0)

    if not results:
        print(f"no paths from {src} to {dst}")
        return

    def sort_key(r):
        p, c, l = r
        ps = " -> ".join(p)
        if g.weighted:
            return (c, l, ps)
        return (l, ps)

    results.sort(key=sort_key)

    for path, cost, length in results:
        ps = " -> ".join(path)
        if g.weighted:
            print(f"{ps} (cost: {cost:.1f}, length: {length})")
        else:
            print(f"{ps} (length: {length})")


def cmd_serialize(g):
    data = bytearray()
    # Magic
    data += b"GRB\x01"
    # Flags
    flags = 0x01 if g.weighted else 0x00
    data += struct.pack("<B", flags)
    # Nodes sorted
    nodes = sorted(g.nodes)
    data += struct.pack("<I", len(nodes))
    node_idx = {}
    for i, n in enumerate(nodes):
        node_idx[n] = i
        name_bytes = n.encode("ascii")
        data += struct.pack("<B", len(name_bytes))
        data += name_bytes
    # Edges sorted by src then dst
    edges = []
    for src_name in nodes:
        sorted_edges = sorted(g.adj[src_name], key=lambda e: e[0])
        for dst_name, w in sorted_edges:
            edges.append((node_idx[src_name], node_idx[dst_name], w))
    data += struct.pack("<I", len(edges))
    for si, di, w in edges:
        data += struct.pack("<I", si)
        data += struct.pack("<I", di)
        if g.weighted:
            data += struct.pack("<d", w)
    # CRC32
    crc = zlib.crc32(bytes(data)) & 0xFFFFFFFF
    data += struct.pack("<I", crc)
    sys.stdout.buffer.write(bytes(data))


def cmd_deserialize(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except (FileNotFoundError, IOError):
        die(f"cannot read file: {path}")

    if len(data) < 13:
        die("invalid binary format")

    payload = data[:-4]
    stored_crc = struct.unpack("<I", data[-4:])[0]
    if (zlib.crc32(payload) & 0xFFFFFFFF) != stored_crc:
        die("checksum mismatch")

    pos = 0
    magic = payload[pos : pos + 4]
    pos += 4
    if magic != b"GRB\x01":
        die("invalid magic")

    flags = payload[pos]
    pos += 1
    weighted = bool(flags & 0x01)

    num_nodes = struct.unpack("<I", payload[pos : pos + 4])[0]
    pos += 4
    nodes = []
    for _ in range(num_nodes):
        name_len = payload[pos]
        pos += 1
        name = payload[pos : pos + name_len].decode("ascii")
        pos += name_len
        nodes.append(name)

    num_edges = struct.unpack("<I", payload[pos : pos + 4])[0]
    pos += 4
    edges = []
    for _ in range(num_edges):
        si = struct.unpack("<I", payload[pos : pos + 4])[0]
        pos += 4
        di = struct.unpack("<I", payload[pos : pos + 4])[0]
        pos += 4
        w = 1.0
        if weighted:
            w = struct.unpack("<d", payload[pos : pos + 8])[0]
            pos += 8
        edges.append((nodes[si], nodes[di], w))

    if weighted:
        print("@weighted")
    for n in nodes:
        print(f"node {n}")
    for src, dst, w in edges:
        if weighted:
            print(f"edge {src} -> {dst} {w:.1f}")
        else:
            print(f"edge {src} -> {dst}")


def cmd_pagerank(g, damping=0.85, max_iter=100):
    nodes = sorted(g.nodes)
    n = len(nodes)
    if n == 0:
        return

    node_idx = {nd: i for i, nd in enumerate(nodes)}

    rank = [1.0 / n] * n
    out_deg = [len(g.adj[nd]) for nd in nodes]

    for _ in range(max_iter):
        new_rank = [0.0] * n

        dangling_sum = sum(rank[i] for i in range(n) if out_deg[i] == 0)

        base = (1.0 - damping + damping * dangling_sum) / n
        for i in range(n):
            new_rank[i] = base

        for i, nd in enumerate(nodes):
            if out_deg[i] > 0:
                share = damping * rank[i] / out_deg[i]
                for nbr, _ in g.adj[nd]:
                    j = node_idx[nbr]
                    new_rank[j] += share

        diff = sum(abs(new_rank[i] - rank[i]) for i in range(n))
        rank = new_rank
        if diff < 1e-10:
            break

    nrs = [(nodes[i], rank[i]) for i in range(n)]
    nrs.sort(key=lambda x: (-x[1], x[0]))

    for name, r in nrs:
        print(f"{name}: {r:.6f}")


def cmd_scc(g):
    nodes = sorted(g.nodes)
    n = len(nodes)
    if n == 0:
        return

    node_idx = {nd: i for i, nd in enumerate(nodes)}

    idx = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    visited = [False] * n
    stack = []
    counter = [0]
    components = []

    def strongconnect(v):
        idx[v] = counter[0]
        low[v] = counter[0]
        counter[0] += 1
        visited[v] = True
        stack.append(v)
        on_stack[v] = True

        for dst, _ in g.adj[nodes[v]]:
            w = node_idx[dst]
            if not visited[w]:
                strongconnect(w)
                if low[w] < low[v]:
                    low[v] = low[w]
            elif on_stack[w]:
                if idx[w] < low[v]:
                    low[v] = idx[w]

        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(nodes[w])
                if w == v:
                    break
            comp.sort()
            components.append(comp)

    for i in range(n):
        if not visited[i]:
            strongconnect(i)

    components.sort(key=lambda c: c[0])

    for comp in components:
        print("{" + ", ".join(comp) + "}")


def main():
    if len(sys.argv) < 3:
        print(
            "usage: graphtool <command> <file> [args...]", file=sys.stderr
        )
        sys.exit(1)

    cmd = sys.argv[1]
    path = sys.argv[2]

    if cmd == "deserialize":
        cmd_deserialize(path)
        return

    g = parse_graph(path)

    if cmd == "info":
        cmd_info(g)
    elif cmd == "adj":
        cmd_adj(g)
    elif cmd == "shortest":
        if len(sys.argv) != 5:
            print(
                "usage: graphtool shortest <file> <src> <dst>",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_shortest(g, sys.argv[3], sys.argv[4])
    elif cmd == "topo":
        cmd_topo(g)
    elif cmd == "allpaths":
        if len(sys.argv) != 5:
            print(
                "usage: graphtool allpaths <file> <src> <dst>",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_allpaths(g, sys.argv[3], sys.argv[4])
    elif cmd == "serialize":
        cmd_serialize(g)
    elif cmd == "pagerank":
        damping = 0.85
        max_iter = 100
        if len(sys.argv) > 3:
            try:
                damping = float(sys.argv[3])
            except ValueError:
                die("damping factor must be between 0.0 and 1.0")
            if damping < 0 or damping > 1:
                die("damping factor must be between 0.0 and 1.0")
        if len(sys.argv) > 4:
            try:
                max_iter = int(sys.argv[4])
            except ValueError:
                die("iterations must be a positive integer")
            if max_iter < 1:
                die("iterations must be a positive integer")
        cmd_pagerank(g, damping, max_iter)
    elif cmd == "scc":
        cmd_scc(g)
    else:
        die(f"unknown command '{cmd}'")


if __name__ == "__main__":
    main()
