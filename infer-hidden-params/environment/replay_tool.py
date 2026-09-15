#!/usr/bin/env python3
"""CLI tool for interacting with the Lux AI S3 replay database."""

import argparse
import gzip
import json
import os
import sqlite3
import sys

DB_PATH = "/app/replays.db"

REQUIRED_RESULT_KEYS = [
    "nebula_tile_drift_speed",
    "nebula_tile_energy_reduction",
    "nebula_tile_vision_reduction",
    "unit_sap_dropoff_factor",
    "unit_energy_void_factor",
    "energy_node_drift_speed",
    "energy_node_drift_magnitude",
]


def get_db():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def cmd_list(args):
    db = get_db()
    cur = db.execute("SELECT id, num_steps, description FROM replays ORDER BY id")
    rows = cur.fetchall()
    if not rows:
        print("No replays in database.")
        db.close()
        return
    print(f"{'ID':>4}  {'Steps':>6}  Description")
    print("-" * 50)
    for row in rows:
        print(f"{row[0]:>4}  {row[1]:>6}  {row[2] or ''}")
    db.close()


def cmd_info(args):
    db = get_db()
    row = db.execute(
        "SELECT id, num_steps, description FROM replays WHERE id = ?",
        (args.replay_id,),
    ).fetchone()
    if not row:
        print(f"Replay {args.replay_id} not found.", file=sys.stderr)
        db.close()
        sys.exit(1)
    print(f"Replay ID: {row[0]}")
    print(f"Num Steps: {row[1]}")
    print(f"Description: {row[2] or 'N/A'}")

    state_count = db.execute(
        "SELECT COUNT(*) FROM states WHERE replay_id = ?", (args.replay_id,)
    ).fetchone()[0]
    action_count = db.execute(
        "SELECT COUNT(*) FROM actions WHERE replay_id = ?", (args.replay_id,)
    ).fetchone()[0]
    print(f"State snapshots: {state_count}")
    print(f"Action records: {action_count}")

    params = db.execute(
        "SELECT param_name, param_value FROM known_params WHERE replay_id = ? ORDER BY param_name",
        (args.replay_id,),
    ).fetchall()
    if params:
        print("\nKnown Parameters:")
        for name, val in params:
            if val == int(val):
                print(f"  {name}: {int(val)}")
            else:
                print(f"  {name}: {val}")
    db.close()


def cmd_export_state(args):
    db = get_db()
    row = db.execute(
        "SELECT data FROM states WHERE replay_id = ? AND step_idx = ?",
        (args.replay_id, args.step),
    ).fetchone()
    if not row:
        print(
            f"State not found for replay {args.replay_id}, step {args.step}.",
            file=sys.stderr,
        )
        db.close()
        sys.exit(1)
    data = gzip.decompress(row[0])
    if args.output:
        with open(args.output, "wb") as f:
            f.write(data)
        print(f"Exported to {args.output}")
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.write(b"\n")
    db.close()


def cmd_export_actions(args):
    db = get_db()
    row = db.execute(
        "SELECT data FROM actions WHERE replay_id = ? AND step_idx = ?",
        (args.replay_id, args.step),
    ).fetchone()
    if not row:
        print(
            f"Actions not found for replay {args.replay_id}, step {args.step}.",
            file=sys.stderr,
        )
        db.close()
        sys.exit(1)
    data = gzip.decompress(row[0])
    if args.output:
        with open(args.output, "wb") as f:
            f.write(data)
        print(f"Exported to {args.output}")
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.write(b"\n")
    db.close()


def cmd_params(args):
    db = get_db()
    params = db.execute(
        "SELECT param_name, param_value FROM known_params WHERE replay_id = ? ORDER BY param_name",
        (args.replay_id,),
    ).fetchall()
    if not params:
        print(f"No known params for replay {args.replay_id}.", file=sys.stderr)
        db.close()
        sys.exit(1)
    if args.json:
        d = {}
        for name, val in params:
            d[name] = int(val) if val == int(val) else val
        print(json.dumps(d, indent=2))
    else:
        for name, val in params:
            if val == int(val):
                print(f"{name}={int(val)}")
            else:
                print(f"{name}={val}")
    db.close()


def cmd_submit(args):
    db = get_db()
    row = db.execute(
        "SELECT id FROM replays WHERE id = ?", (args.replay_id,)
    ).fetchone()
    if not row:
        print(f"Replay {args.replay_id} not found.", file=sys.stderr)
        db.close()
        sys.exit(1)

    with open(args.json_file) as f:
        results = json.load(f)

    for key in REQUIRED_RESULT_KEYS:
        if key not in results:
            print(f"Missing required key: {key}", file=sys.stderr)
            db.close()
            sys.exit(1)

    for key in REQUIRED_RESULT_KEYS:
        db.execute(
            "INSERT OR REPLACE INTO results (replay_id, param_name, param_value) VALUES (?, ?, ?)",
            (args.replay_id, key, float(results[key])),
        )
    db.commit()
    print(f"Submitted {len(REQUIRED_RESULT_KEYS)} parameters for replay {args.replay_id} to database.")

    os.makedirs("/app/results", exist_ok=True)
    out_path = f"/app/results/replay_{args.replay_id}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_path}")
    db.close()


def cmd_schema(args):
    db = get_db()
    cur = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    for (sql,) in cur:
        if sql:
            print(sql + ";")
            print()
    db.close()


def cmd_verify(args):
    db = get_db()
    replays = db.execute(
        "SELECT id FROM replays WHERE description IS NULL OR description != 'example' ORDER BY id"
    ).fetchall()
    if not replays:
        print("No non-example replays found in database.")
        db.close()
        sys.exit(1)
    all_ok = True
    for (rid,) in replays:
        result_count = db.execute(
            "SELECT COUNT(*) FROM results WHERE replay_id = ?", (rid,)
        ).fetchone()[0]
        json_path = f"/app/results/replay_{rid}.json"
        json_exists = os.path.exists(json_path)
        if result_count < 7 or not json_exists:
            status = "INCOMPLETE"
            print(
                f"Replay {rid}: {status} (db: {result_count}/7 params, json: {'yes' if json_exists else 'no'})"
            )
            all_ok = False
        else:
            print(f"Replay {rid}: OK")
    if all_ok:
        print("\nAll results submitted successfully.")
    else:
        print("\nSome results missing!", file=sys.stderr)
        sys.exit(1)
    db.close()


def cmd_count_steps(args):
    db = get_db()
    row = db.execute(
        "SELECT MIN(step_idx), MAX(step_idx) FROM states WHERE replay_id = ?",
        (args.replay_id,),
    ).fetchone()
    if row[0] is None:
        print(f"No states found for replay {args.replay_id}.", file=sys.stderr)
        db.close()
        sys.exit(1)
    print(f"Step range: {row[0]} to {row[1]}")
    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Lux AI S3 Replay Database Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  replay-tool list                      List all replays
  replay-tool info 0                    Show info for replay 0
  replay-tool schema                    Show database schema
  replay-tool export-state 0 5          Print state at step 5 of replay 0
  replay-tool export-state 0 5 -o s.json  Export state to file
  replay-tool params 0 --json           Get known params as JSON
  replay-tool submit 0 result.json      Submit inferred parameters
  replay-tool verify                    Check all results submitted
  replay-tool steps 0                   Show step range for replay""",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    sub.add_parser("list", help="List all replays in the database")

    p = sub.add_parser("info", help="Show metadata and known params for a replay")
    p.add_argument("replay_id", type=int, help="Replay ID")

    p = sub.add_parser(
        "export-state", help="Export a decompressed state snapshot as JSON"
    )
    p.add_argument("replay_id", type=int, help="Replay ID")
    p.add_argument("step", type=int, help="Step index")
    p.add_argument("-o", "--output", help="Output file path (default: stdout)")

    p = sub.add_parser(
        "export-actions", help="Export decompressed actions for a step as JSON"
    )
    p.add_argument("replay_id", type=int, help="Replay ID")
    p.add_argument("step", type=int, help="Step index")
    p.add_argument("-o", "--output", help="Output file path (default: stdout)")

    p = sub.add_parser("params", help="Show known parameters for a replay")
    p.add_argument("replay_id", type=int, help="Replay ID")
    p.add_argument("--json", action="store_true", help="Output as JSON object")

    p = sub.add_parser("submit", help="Submit inferred parameters for a replay")
    p.add_argument("replay_id", type=int, help="Replay ID")
    p.add_argument("json_file", help="Path to JSON file with inferred parameters")

    sub.add_parser("schema", help="Show database table definitions")

    sub.add_parser(
        "verify", help="Verify all non-example replays have complete results"
    )

    p = sub.add_parser("steps", help="Show step range for a replay")
    p.add_argument("replay_id", type=int, help="Replay ID")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "list": cmd_list,
        "info": cmd_info,
        "export-state": cmd_export_state,
        "export-actions": cmd_export_actions,
        "params": cmd_params,
        "submit": cmd_submit,
        "schema": cmd_schema,
        "verify": cmd_verify,
        "steps": cmd_count_steps,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
