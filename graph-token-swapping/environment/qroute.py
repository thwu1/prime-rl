#!/usr/bin/env python3
"""
Quantum SWAP route compiler — benchmark runner, device topology analyzer,
and Graphviz/JSON export tool.

Reads benchmark metadata from SQLite database (/app/devices.db) and
device connectivity from Graphviz DOT files (/app/devices/).

"""

import argparse
import json
import sqlite3
import sys
import os
import random
import re

DB_PATH = "/app/devices.db"
DEVICES_DIR = "/app/devices"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_dot_edges(dot_file):
    """Extract edges from a Graphviz DOT file."""
    edges = []
    dot_path = os.path.join(DEVICES_DIR, dot_file) if not os.path.isabs(dot_file) else dot_file
    with open(dot_path) as f:
        for line in f:
            m = re.match(r'\s*(\d+)\s*--\s*(\d+)\s*;', line)
            if m:
                u, v = int(m.group(1)), int(m.group(2))
                edges.append([u, v])
    return edges


def load_benchmark(conn, name):
    """Load a full benchmark specification from SQLite + DOT file."""
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, b.name, b.description, b.max_swaps, b.perm_type, b.perm_seed,
               d.qubits, d.dot_file, d.name as device_name, d.description as device_desc
        FROM benchmarks b
        JOIN devices d ON b.device_id = d.id
        WHERE b.name = ?
    """, (name,))
    row = cur.fetchone()
    if row is None:
        return None

    n = row['qubits']
    edges = parse_dot_edges(row['dot_file'])

    if row['perm_type'] == 'explicit':
        cur.execute(
            "SELECT target FROM explicit_permutations WHERE benchmark_id = ? ORDER BY position",
            (row['id'],)
        )
        perm = [r['target'] for r in cur.fetchall()]
    elif row['perm_type'] == 'seeded_random':
        rng = random.Random(row['perm_seed'])
        perm = list(range(n))
        rng.shuffle(perm)
    else:
        raise ValueError("Unknown perm_type: %s" % row['perm_type'])

    return {
        'name': row['name'],
        'description': row['description'],
        'n': n,
        'edges': edges,
        'perm': perm,
        'max_swaps': row['max_swaps'],
        'device_name': row['device_name'],
        'device_desc': row['device_desc'],
        'dot_file': row['dot_file'],
    }


def load_all_benchmarks(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM benchmarks ORDER BY id")
    return [load_benchmark(conn, r['name']) for r in cur.fetchall()]


def analyze_topology(edges, n):
    """Compute structural properties of a device topology graph."""
    m = len(edges)
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    degrees = [len(adj[i]) for i in range(n)]
    deg_min = min(degrees) if degrees else 0
    deg_max = max(degrees) if degrees else 0

    is_tree = (m == n - 1)
    is_complete = (m == n * (n - 1) // 2)
    is_path = is_tree and deg_max <= 2
    is_cycle = (m == n) and all(d == 2 for d in degrees)
    is_star = is_tree and deg_max == n - 1 and n > 2

    diameter = None
    if n <= 200:
        from collections import deque

        def bfs_dist(src):
            dist = [-1] * n
            dist[src] = 0
            q = deque([src])
            while q:
                v = q.popleft()
                for u in adj[v]:
                    if dist[u] == -1:
                        dist[u] = dist[v] + 1
                        q.append(u)
            return max(dist)

        diameter = bfs_dist(0)

    deg_hist = {}
    for d in degrees:
        deg_hist[d] = deg_hist.get(d, 0) + 1

    return {
        "qubits": n,
        "connections": m,
        "degree_min": deg_min,
        "degree_max": deg_max,
        "degree_histogram": deg_hist,
        "is_tree": is_tree,
        "is_path": is_path,
        "is_cycle": is_cycle,
        "is_star": is_star,
        "is_complete": is_complete,
        "diameter": diameter,
    }


def validate_solution(n, edges, perm, swaps):
    """Validate a SWAP sequence for correctness."""
    edge_set = set()
    for e in edges:
        edge_set.add((min(e[0], e[1]), max(e[0], e[1])))

    state = list(range(n))
    for idx, s in enumerate(swaps):
        u, v = s[0], s[1]
        key = (min(u, v), max(u, v))
        if key not in edge_set:
            return False, "swap #%d (%d,%d) is not a device edge" % (idx, u, v)
        if not (0 <= u < n and 0 <= v < n):
            return False, "swap #%d (%d,%d) out of qubit range [0, %d)" % (idx, u, v, n)
        state[u], state[v] = state[v], state[u]

    if state != perm:
        got = str(state[:20]) + ("..." if n > 20 else "")
        exp = str(perm[:20]) + ("..." if n > 20 else "")
        return False, "final arrangement does not match target\n  got:      %s\n  expected: %s" % (got, exp)

    return True, len(swaps)


def cmd_list(args):
    conn = get_db()
    benchmarks = load_all_benchmarks(conn)
    print("%-30s %6s %6s %7s  %s" % ("Name", "Qubits", "Edges", "Bound", "Description"))
    print("-" * 85)
    for b in benchmarks:
        print("%-30s %6d %6d %7d  %s" % (b['name'], b['n'], len(b['edges']), b['max_swaps'], b['description']))
    print("\n%d benchmarks total" % len(benchmarks))
    conn.close()


def cmd_info(args):
    conn = get_db()
    bench = load_benchmark(conn, args.name)
    if bench is None:
        print("Error: benchmark '%s' not found" % args.name, file=sys.stderr)
        print("Use 'list' to see available benchmarks.", file=sys.stderr)
        sys.exit(1)

    props = analyze_topology(bench['edges'], bench['n'])
    n = bench['n']

    print("Benchmark: %s" % bench['name'])
    print("  Device: %s" % bench['device_name'])
    print("  Description: %s" % bench['description'])
    print("  DOT file: %s/%s" % (DEVICES_DIR, bench['dot_file']))
    print("  Qubits: %d" % props['qubits'])
    print("  Connections: %d" % props['connections'])
    print("  Degree range: %d\u2013%d" % (props['degree_min'], props['degree_max']))

    structure = []
    if props["is_path"]:
        structure.append("linear chain (path)")
    elif props["is_star"]:
        structure.append("star")
    elif props["is_cycle"]:
        structure.append("ring (cycle)")
    elif props["is_complete"]:
        structure.append("fully connected (complete)")
    elif props["is_tree"]:
        structure.append("tree")
    else:
        structure.append("general connected graph")
    print("  Topology class: %s" % ", ".join(structure))

    deg_hist = props["degree_histogram"]
    hist_str = ", ".join("deg %d: %d nodes" % (k, v) for k, v in sorted(deg_hist.items()))
    print("  Degree distribution: %s" % hist_str)

    if props["diameter"] is not None:
        print("  BFS depth from node 0: %d" % props['diameter'])

    perm = bench['perm']
    if n <= 30:
        print("  Target mapping: %s" % perm)
    else:
        print("  Target mapping: [%d, %d, %d, ..., %d] (%d elements)" % (perm[0], perm[1], perm[2], perm[-1], n))

    edges = bench['edges']
    if n <= 30:
        print("  Edge list: %s" % edges)
    else:
        print("  Edge list: [%s, %s, ..., %s] (%d edges)" % (edges[0], edges[1], edges[-1], len(edges)))

    print("  Quality bound: %d swaps maximum" % bench['max_swaps'])

    # Show topology properties from database
    cur = conn.cursor()
    cur.execute("""
        SELECT tp.property, tp.value FROM topology_properties tp
        JOIN devices d ON tp.device_id = d.id
        JOIN benchmarks b ON b.device_id = d.id
        WHERE b.name = ?
        ORDER BY tp.property
    """, (args.name,))
    tp_rows = cur.fetchall()
    if tp_rows:
        print("  Topology properties (from database):")
        for r in tp_rows:
            print("    %s: %s" % (r['property'], r['value']))

    conn.close()


def cmd_dot(args):
    """Output Graphviz DOT source for a device topology."""
    conn = get_db()
    bench = load_benchmark(conn, args.name)
    if bench is None:
        print("Error: benchmark '%s' not found" % args.name, file=sys.stderr)
        sys.exit(1)

    dot_path = os.path.join(DEVICES_DIR, bench['dot_file'])
    with open(dot_path) as f:
        sys.stdout.write(f.read())
    conn.close()


def cmd_export(args):
    """Export benchmark specification as JSON."""
    conn = get_db()
    if args.name == "all":
        benchmarks = load_all_benchmarks(conn)
        data = []
        for b in benchmarks:
            data.append({
                "name": b['name'],
                "description": b['description'],
                "device": b['device_name'],
                "qubits": b['n'],
                "edges": b['edges'],
                "permutation": b['perm'],
                "max_swaps": b['max_swaps'],
                "dot_file": b['dot_file'],
            })
        print(json.dumps(data, indent=2))
    else:
        bench = load_benchmark(conn, args.name)
        if bench is None:
            print("Error: benchmark '%s' not found" % args.name, file=sys.stderr)
            sys.exit(1)
        data = {
            "name": bench['name'],
            "description": bench['description'],
            "device": bench['device_name'],
            "qubits": bench['n'],
            "edges": bench['edges'],
            "permutation": bench['perm'],
            "max_swaps": bench['max_swaps'],
            "dot_file": bench['dot_file'],
        }
        print(json.dumps(data, indent=2))
    conn.close()


def cmd_test(args):
    conn = get_db()

    if args.name == "all":
        targets = load_all_benchmarks(conn)
    else:
        bench = load_benchmark(conn, args.name)
        if bench is None:
            print("Error: benchmark '%s' not found" % args.name, file=sys.stderr)
            sys.exit(1)
        targets = [bench]

    sys.path.insert(0, "/app")
    try:
        from solver import solve
    except ImportError as e:
        print("Error: cannot import solver \u2014 %s" % e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("Error loading solver: %s" % e, file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    errors = 0

    for bench in targets:
        name = bench['name']
        n = bench['n']
        edges = bench['edges']
        perm = bench['perm']
        max_swaps = bench['max_swaps']

        try:
            swaps = solve(n, edges, perm)

            if not isinstance(swaps, list):
                print("  %-30s FAIL  (solver did not return a list)" % name)
                failed += 1
                continue

            valid, result = validate_solution(n, edges, perm, swaps)

            if not valid:
                print("  %-30s FAIL  (%s)" % (name, result))
                failed += 1
            elif len(swaps) > max_swaps:
                print("  %-30s FAIL  (%d swaps exceeds bound of %d)" % (name, len(swaps), max_swaps))
                failed += 1
            else:
                print("  %-30s PASS  (%d swaps, bound %d)" % (name, len(swaps), max_swaps))
                passed += 1

        except NotImplementedError:
            print("  %-30s SKIP  (not implemented)" % name)
            errors += 1
        except Exception as e:
            print("  %-30s ERROR (%s: %s)" % (name, type(e).__name__, e))
            errors += 1

    total = passed + failed + errors
    sys.stdout.write("\nResults: %d/%d passed" % (passed, total))
    if failed:
        sys.stdout.write(", %d failed" % failed)
    if errors:
        sys.stdout.write(", %d errors" % errors)
    print()

    conn.close()
    return 0 if failed == 0 and errors == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Quantum SWAP route compiler \u2014 benchmark runner and topology analyzer.\n"
                    "Data sources: SQLite database (devices.db) + Graphviz DOT files (devices/)"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="List all available benchmarks")

    info_p = subparsers.add_parser("info", help="Show device topology details for a benchmark")
    info_p.add_argument("name", help="Benchmark name")

    dot_p = subparsers.add_parser("dot", help="Output Graphviz DOT source for device topology")
    dot_p.add_argument("name", help="Benchmark name")

    export_p = subparsers.add_parser("export", help="Export benchmark specification as JSON")
    export_p.add_argument("name", help="Benchmark name, or 'all'")

    test_p = subparsers.add_parser("test", help="Test solver against benchmark(s)")
    test_p.add_argument("name", help="Benchmark name, or 'all' to run everything")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "info":
        cmd_info(args)
    elif args.command == "dot":
        cmd_dot(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "test":
        rc = cmd_test(args)
        sys.exit(rc)
    else:
        parser.print_help()
        print("\nCommands:")
        print("  list          List all benchmarks with bounds")
        print("  info NAME     Show device topology analysis for a benchmark")
        print("  dot NAME      Output Graphviz DOT source (pipe to: dot -Tpng > graph.png)")
        print("  export NAME   Export benchmark spec as JSON (pipe to: jq)")
        print("  test NAME     Test solver against a benchmark (or 'all')")


if __name__ == "__main__":
    main()
