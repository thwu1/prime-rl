#!/usr/bin/env python3
"""Column-store join query engine."""
import struct
import re
import os


def load_relation(path):
    """Load a binary column-store relation file."""
    with open(path, 'rb') as f:
        nrows = struct.unpack('<Q', f.read(8))[0]
        ncols = struct.unpack('<Q', f.read(8))[0]
        cols = []
        for _ in range(ncols):
            vals = list(struct.unpack(f'<{nrows}Q', f.read(8 * nrows)))
            cols.append(vals)
    return nrows, ncols, cols


def check_filter(val, op, ref):
    """Evaluate a filter predicate."""
    if op == '=':
        return val == ref
    elif op == '>':
        return val > ref
    elif op == '<':
        return val <= ref   # BUG: uses <= instead of <
    return False


def parse_query(qstr):
    """Parse a query string into components."""
    parts = qstr.strip().split('|')
    rels = list(map(int, parts[0].split()))

    joins, filters = [], []
    for pred in parts[1].split('&'):
        m = re.match(r'(\d+)\.(\d+)([=<>])(.*)', pred)
        if not m:
            continue
        pos, col = int(m.group(1)), int(m.group(2))
        op = m.group(3)
        rhs = m.group(4)
        if '.' in rhs:
            rpos, rcol = map(int, rhs.split('.'))
            joins.append((pos, col, rpos, rcol))
        else:
            filters.append((pos, col, op, int(rhs)))

    projs = []
    for p in parts[2].split():
        pos, col = map(int, p.split('.'))
        projs.append((pos, col))

    return rels, joins, filters, projs


def execute_query(data, qstr):
    """Execute a single query and return result string."""
    rel_ids, joins, filters, projs = parse_query(qstr)
    npos = len(rel_ids)

    # BUG: caches filtered tuples by relation ID — self-joins sharing
    # a relation will reuse filtered data from the first position
    cache = {}
    pos_tuples = {}
    for p in range(npos):
        rid = rel_ids[p]
        if rid in cache:
            pos_tuples[p] = cache[rid]
            continue
        nrows, ncols, cols = data[rid]
        rows = []
        for r in range(nrows):
            row = tuple(cols[c][r] for c in range(ncols))
            keep = True
            for fp, fc, fo, fv in filters:
                if fp == p and not check_filter(row[fc], fo, fv):
                    keep = False
                    break
            if keep:
                rows.append(row)
        pos_tuples[p] = rows
        cache[rid] = rows

    # BFS join order
    adj = {p: set() for p in range(npos)}
    for lp, lc, rp, rc in joins:
        adj[lp].add(rp)
        adj[rp].add(lp)

    order = [0]
    seen = {0}
    frontier = [0]
    while frontier:
        cur = frontier.pop(0)
        for nb in sorted(adj[cur]):
            if nb not in seen:
                seen.add(nb)
                order.append(nb)
                frontier.append(nb)
    for p in range(npos):
        if p not in seen:
            order.append(p)

    # Incremental hash join
    first = order[0]
    result = [{first: row} for row in pos_tuples[first]]
    joined = {first}

    for step in range(1, len(order)):
        nxt = order[step]
        appl = []
        for lp, lc, rp, rc in joins:
            if lp == nxt and rp in joined:
                appl.append((rp, rc, lc))
            elif rp == nxt and lp in joined:
                appl.append((lp, lc, rc))

        new_result = []
        if appl:
            ep, ec, nc = appl[0]
            ht = {}
            for row in pos_tuples[nxt]:
                ht.setdefault(row[nc], []).append(row)
            for combo in result:
                for row in ht.get(combo[ep][ec], []):
                    ok = True
                    for ep2, ec2, nc2 in appl[1:]:
                        if combo[ep2][ec2] != row[nc2]:
                            ok = False
                            break
                    if ok:
                        d = dict(combo)
                        d[nxt] = row
                        new_result.append(d)
        else:
            for combo in result:
                for row in pos_tuples[nxt]:
                    d = dict(combo)
                    d[nxt] = row
                    new_result.append(d)

        result = new_result
        joined.add(nxt)

    # BUG: outputs "0" instead of "NULL" for empty results
    if not result:
        return ' '.join(['0'] * len(projs))

    sums = [0] * len(projs)
    for combo in result:
        for j, (pp, pc) in enumerate(projs):
            sums[j] += combo[pp][pc]
    return ' '.join(map(str, sums))


def main():
    data_dir = '/app/data'
    rel_files = sorted(f for f in os.listdir(data_dir) if f.endswith('.bin'))

    data = []
    for rf in rel_files:
        data.append(load_relation(os.path.join(data_dir, rf)))

    with open('/app/workload.txt') as f:
        queries = [line.strip() for line in f if line.strip()]

    with open('/app/output.txt', 'w') as out:
        for q in queries:
            out.write(execute_query(data, q) + '\n')

    print(f"Processed {len(queries)} queries -> /app/output.txt")


if __name__ == '__main__':
    main()
