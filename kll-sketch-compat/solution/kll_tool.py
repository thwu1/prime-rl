#!/usr/bin/env python3
"""KLL sketch CLI tool with SQLite persistence and JSON output."""


import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")
from kll_sketch import KllDoublesSketch

DB_PATH = "/app/sketch_store.db"


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS sketches (
        name        TEXT PRIMARY KEY,
        k           INTEGER NOT NULL,
        n           INTEGER NOT NULL,
        created_at  TEXT NOT NULL,
        sketch_blob BLOB NOT NULL
    )""")
    return conn


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sketch_to_json(name, sketch, created_at):
    if sketch.is_empty:
        quantiles = None
        min_val = None
        max_val = None
    else:
        quantiles = {
            "0.0": sketch.get_quantile(0.0),
            "0.25": sketch.get_quantile(0.25),
            "0.5": sketch.get_quantile(0.5),
            "0.75": sketch.get_quantile(0.75),
            "1.0": sketch.get_quantile(1.0),
        }
        min_val = sketch.min_value
        max_val = sketch.max_value

    return {
        "name": name,
        "k": sketch.k,
        "n": sketch.n,
        "min_value": min_val,
        "max_value": max_val,
        "is_empty": sketch.is_empty,
        "is_estimation_mode": sketch.is_estimation_mode,
        "num_retained": sketch.num_retained,
        "quantiles": quantiles,
        "created_at": created_at,
    }


def _store_sketch(conn, name, sketch, created_at):
    blob = sketch.serialize()
    conn.execute(
        "INSERT OR REPLACE INTO sketches (name, k, n, created_at, sketch_blob) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, sketch.k, sketch.n, created_at, blob),
    )
    conn.commit()


def _load_sketch(conn, name):
    row = conn.execute(
        "SELECT k, n, created_at, sketch_blob FROM sketches WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return None, None
    _, _, created_at, blob = row
    sketch = KllDoublesSketch.deserialize(blob)
    return sketch, created_at


def cmd_ingest(args):
    k = args.k if args.k else 200
    sketch = KllDoublesSketch(k)
    for line in sys.stdin:
        line = line.strip()
        if line:
            try:
                sketch.update(float(line))
            except ValueError:
                pass

    now = _now_iso()
    conn = _get_db()
    _store_sketch(conn, args.name, sketch, now)
    print(json.dumps(_sketch_to_json(args.name, sketch, now)))
    conn.close()


def cmd_inspect(args):
    conn = _get_db()
    sketch, created_at = _load_sketch(conn, args.name)
    conn.close()
    if sketch is None:
        print(json.dumps({"error": f"sketch '{args.name}' not found"}))
        sys.exit(1)
    print(json.dumps(_sketch_to_json(args.name, sketch, created_at)))


def cmd_merge(args):
    conn = _get_db()
    sketches = []
    for name in args.inputs:
        sketch, _ = _load_sketch(conn, name)
        if sketch is None:
            conn.close()
            print(json.dumps({"error": f"sketch '{name}' not found"}))
            sys.exit(1)
        sketches.append(sketch)

    merged = sketches[0]
    for s in sketches[1:]:
        merged.merge(s)

    now = _now_iso()
    _store_sketch(conn, args.output, merged, now)
    print(json.dumps(_sketch_to_json(args.output, merged, now)))
    conn.close()


def cmd_export(args):
    conn = _get_db()
    row = conn.execute(
        "SELECT sketch_blob FROM sketches WHERE name = ?", (args.name,)
    ).fetchone()
    conn.close()
    if row is None:
        print(json.dumps({"error": f"sketch '{args.name}' not found"}))
        sys.exit(1)
    sys.stdout.buffer.write(row[0])


def cmd_import(args):
    blob = sys.stdin.buffer.read()
    if not blob:
        print(json.dumps({"error": "no binary data on stdin"}))
        sys.exit(1)
    try:
        sketch = KllDoublesSketch.deserialize(blob)
    except Exception as e:
        print(json.dumps({"error": f"invalid sketch data: {e}"}))
        sys.exit(1)

    now = _now_iso()
    conn = _get_db()
    _store_sketch(conn, args.name, sketch, now)
    print(json.dumps(_sketch_to_json(args.name, sketch, now)))
    conn.close()


def main():
    parser = argparse.ArgumentParser(prog="kll_tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--name", required=True)
    p_ingest.add_argument("--k", type=int, default=None)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("--name", required=True)

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("--output", required=True)
    p_merge.add_argument("--inputs", nargs="+", required=True)

    p_export = sub.add_parser("export")
    p_export.add_argument("--name", required=True)

    p_import = sub.add_parser("import")
    p_import.add_argument("--name", required=True)

    args = parser.parse_args()

    dispatch = {
        "ingest": cmd_ingest,
        "inspect": cmd_inspect,
        "merge": cmd_merge,
        "export": cmd_export,
        "import": cmd_import,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
