#!/usr/bin/env python3
"""Oracle solution: regenerate ground truth from deterministic seed, execute queries."""

import random
import re
import os

NUM_RELATIONS = 6

SPECS = [
    (200, 4, 1, 50),
    (300, 3, 1, 50),
    (150, 4, 1, 40),
    (400, 3, 1, 50),
    (250, 4, 1, 50),
    (180, 3, 1, 50),
]

QUERIES = [
    "0 1|0.0=1.0|0.2 1.2",
    "0 3|0.1=1.1|0.2 1.2",
    "1 3|0.0=1.0&1.2<30|0.2 1.2",
    "0 2|0.0=1.0|0.2 1.2",
    "0 4|0.0=1.0|0.2 1.2",
    "2 5|0.1=1.1|0.0 1.2",
    "3 5|0.0=1.0|0.2 1.2",
    "1 5|0.0=1.0|0.1 1.1",
    "0 1|0.0=1.0&0.2<25|0.3 1.2",
    "0 3|0.1=1.1&0.3<20|0.2 1.2",
    "0 1|0.0=1.0&0.2>30|0.3 1.1",
    "1 5|0.0=1.0&0.1<20|0.2 1.1",
    "0 0|0.0=1.0&1.2>30|0.3 1.3",
    "0 0|0.0=1.0&0.2>20|0.3 1.3",
    "0 0|0.0=1.0|0.2 1.3",
    "1 1|0.0=1.1&0.1>25|0.2 1.2",
    "3 3|0.0=1.0&0.1>25|0.1 1.1",
    "0 1|0.0=1.0&0.2>999|0.3 1.2",
    "0 3|0.1=1.1&0.3>999|0.2 1.2",
    "0 1 3|0.0=1.0&1.0=2.0|0.3 2.2",
    "0 1 2|0.0=1.0&1.0=2.0|0.3 2.3",
    "0 1 3|0.0=1.0&1.0=2.0&0.2<30|0.3 1.2 2.2",
    "0 3 4|0.0=1.0&1.0=2.0|0.3 2.3",
    "0 0 2|0.0=1.0&1.0=2.0&0.2>20|0.3 2.2",
    "0 3|0.0=1.0&0.2=25|0.1 1.2",
]


def generate_ground_truth():
    """Regenerate correct relation data from deterministic seed 42."""
    rng = random.Random(42)
    relations = []
    for nrows, ncols, lo, hi in SPECS:
        cols = [[rng.randint(lo, hi) for _ in range(nrows)] for _ in range(ncols)]
        relations.append((nrows, ncols, cols))
    return relations


def check_filter(val, op, ref):
    if op == '=':
        return val == ref
    if op == '>':
        return val > ref
    if op == '<':
        return val < ref
    return False


def parse_query(qstr):
    parts = qstr.strip().split('|')
    rels = list(map(int, parts[0].split()))
    joins, filters = [], []
    for pred in parts[1].split('&'):
        m = re.match(r'(\d+)\.(\d+)([=<>])(.*)', pred)
        if not m:
            continue
        p, c = int(m.group(1)), int(m.group(2))
        op = m.group(3)
        rhs = m.group(4)
        if '.' in rhs:
            rp, rc = map(int, rhs.split('.'))
            joins.append((p, c, rp, rc))
        else:
            filters.append((p, c, op, int(rhs)))
    projs = []
    for x in parts[2].split():
        p, c = map(int, x.split('.'))
        projs.append((p, c))
    return rels, joins, filters, projs


def execute_query(relations, qstr):
    """Execute query with correct semantics."""
    rel_ids, joins, filters, projs = parse_query(qstr)
    npos = len(rel_ids)

    # Independent filtered tuple sets per position
    pos_tuples = {}
    for p in range(npos):
        rid = rel_ids[p]
        nrows, ncols, cols = relations[rid]
        rows = []
        for r in range(nrows):
            row = [cols[c][r] for c in range(ncols)]
            keep = True
            for fp, fc, fo, fv in filters:
                if fp == p and not check_filter(row[fc], fo, fv):
                    keep = False
                    break
            if keep:
                rows.append(row)
        pos_tuples[p] = rows

    # BFS join order
    adj = {p: set() for p in range(npos)}
    for lp, lc, rp, rc in joins:
        adj[lp].add(rp)
        adj[rp].add(lp)
    order = [0]
    seen = {0}
    q = [0]
    while q:
        cur = q.pop(0)
        for nb in sorted(adj[cur]):
            if nb not in seen:
                seen.add(nb)
                order.append(nb)
                q.append(nb)
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

    if not result:
        return ' '.join(['NULL'] * len(projs))

    sums = [0] * len(projs)
    for combo in result:
        for j, (pp, pc) in enumerate(projs):
            sums[j] += combo[pp][pc]
    return ' '.join(str(s) for s in sums)


def main():
    relations = generate_ground_truth()

    with open('/app/output.txt', 'w') as out:
        for q in QUERIES:
            out.write(execute_query(relations, q) + '\n')

    print(f"Processed {len(QUERIES)} queries -> /app/output.txt")


if __name__ == '__main__':
    main()
