#!/usr/bin/env python3
"""
dessim - Deterministic Event Simulator for primary-backup replicated register clusters.

Diagnostic tool for running and analyzing deterministic simulation traces
from distributed primary-backup replication systems with fault injection.
Inspired by MadSim (madsim-rs/madsim) deterministic simulation framework.

Commands:
    dessim run --config FILE --db FILE [--seed N]
    dessim info --db FILE
    dessim trace --db FILE --run-id N
    dessim ops --db FILE --run-id N
    dessim states --db FILE --run-id N [--time T]
    dessim query --db FILE SQL
    dessim schema
    dessim check-config FILE
"""

import argparse
import json
import os
import random
import sqlite3
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    node_count INTEGER NOT NULL,
    duration REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    time REAL NOT NULL,
    type TEXT NOT NULL,
    node_id INTEGER,
    details_json TEXT
);
CREATE TABLE IF NOT EXISTS operations (
    op_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    client_id INTEGER NOT NULL,
    op_type TEXT NOT NULL CHECK(op_type IN ('read','write')),
    arg INTEGER,
    invoke_time REAL NOT NULL,
    response_time REAL,
    response_value TEXT,
    target_node INTEGER
);
CREATE TABLE IF NOT EXISTS node_states (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    time REAL NOT NULL,
    node_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    value INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    log_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, time);
CREATE INDEX IF NOT EXISTS idx_ops_run ON operations(run_id, invoke_time);
CREATE INDEX IF NOT EXISTS idx_states_run ON node_states(run_id, time);
"""


class Node:
    __slots__ = ("nid", "role", "value", "epoch", "log", "last_hb")

    def __init__(self, nid, role="secondary"):
        self.nid = nid
        self.role = role
        self.value = 0
        self.epoch = 0
        self.log = []
        self.last_hb = 0.0


class Simulator:
    """Deterministic discrete-event simulator for primary-backup replication."""

    def __init__(self, config, seed):
        self.rng = random.Random(seed)
        self.seed = seed
        self.cfg = config
        sim = config.get("simulation", {})
        self.n_nodes = sim.get("node_count", 5)
        self.duration = float(sim.get("duration", 1000))
        self.election_timeout = float(sim.get("election_timeout", 100.0))

        self.nodes = {}
        for i in range(self.n_nodes):
            self.nodes[i] = Node(i, "primary" if i == 0 else "secondary")

        self.partitions = set()
        self.events_log = []
        self.ops_log = []
        self.snapshots = []
        self.t = 0.0
        self.eq = []

        self._schedule_clients()
        self._schedule_faults()
        self.eq.sort(key=lambda x: x[0])

    def _schedule_clients(self):
        cc = self.cfg.get("clients", {})
        n_clients = cc.get("count", 3)
        interval = float(cc.get("request_interval", 40.0))
        wr = float(cc.get("write_ratio", 0.5))
        for c in range(n_clients):
            t = self.rng.uniform(5, 25)
            while t < self.duration:
                if self.rng.random() < wr:
                    v = self.rng.randint(1, 100)
                    self.eq.append((t, "client_write", {"cid": c, "val": v}))
                else:
                    self.eq.append((t, "client_read", {"cid": c}))
                t += interval + self.rng.uniform(-interval * 0.2, interval * 0.2)

    def _schedule_faults(self):
        for f in self.cfg.get("faults", {}).get("schedule", []):
            ft = float(f["time"])
            tp = f["type"]
            if tp == "crash":
                tgt = f.get("target", "primary")
                self.eq.append((ft, "crash", {"target": tgt}))
                ra = f.get("recover_after")
                if ra is not None:
                    self.eq.append((ft + float(ra), "recover", {"target": tgt}))
            elif tp == "partition":
                sa = f.get("set_a", [0])
                sb = f.get("set_b", list(range(1, self.n_nodes)))
                self.eq.append((ft, "partition", {"set_a": sa, "set_b": sb}))
                ha = f.get("heal_after")
                if ha is not None:
                    self.eq.append((ft + float(ha), "heal", {}))

    def _reachable(self, a, b):
        return (a, b) not in self.partitions

    def _find_primary_for(self, home_node):
        """Find a primary reachable from home_node."""
        for n in self.nodes.values():
            if n.role == "primary" and self._reachable(home_node, n.nid):
                return n
        return None

    def _alive_nodes(self):
        return [n for n in self.nodes.values() if n.role != "crashed"]

    def _evt(self, t, tp, nid, det):
        self.events_log.append({"time": t, "type": tp, "node_id": nid, "details": det})

    def _snap(self, t):
        for n in self.nodes.values():
            self.snapshots.append({
                "time": t, "node_id": n.nid, "role": n.role,
                "value": n.value, "epoch": n.epoch, "log": list(n.log),
            })

    def _elect(self, t):
        primaries = [n for n in self.nodes.values() if n.role == "primary"]
        if primaries:
            return
        cands = [n for n in self.nodes.values() if n.role == "secondary"]
        if not cands:
            return
        winner = max(cands, key=lambda n: (len(n.log), -n.nid))
        winner.role = "primary"
        winner.epoch += 1
        self._evt(t, "election", winner.nid, {"epoch": winner.epoch})

    def _elect_in_partition(self, t, node_set):
        """Elect among a specific set of nodes if no primary is reachable."""
        reachable_primaries = [
            n for n in self.nodes.values()
            if n.role == "primary" and n.nid in node_set
        ]
        if reachable_primaries:
            return
        cands = [
            n for n in self.nodes.values()
            if n.role == "secondary" and n.nid in node_set
        ]
        if not cands:
            return
        winner = max(cands, key=lambda n: (len(n.log), -n.nid))
        winner.role = "primary"
        winner.epoch += 1
        self._evt(t, "election", winner.nid,
                  {"epoch": winner.epoch, "partition_set": list(node_set)})

    def run(self):
        self._snap(0)
        while self.eq:
            t, tp, det = self.eq.pop(0)
            if t > self.duration:
                break
            self.t = t
            handler = getattr(self, "_h_" + tp, None)
            if handler:
                handler(t, det)
        self._snap(self.t)

    def _h_client_write(self, t, d):
        cid, val = d["cid"], d["val"]
        home = cid % self.n_nodes
        primary = self._find_primary_for(home)
        if primary is None:
            self.ops_log.append({
                "cid": cid, "op": "write", "arg": val,
                "inv": t, "resp": None, "rval": None, "tgt": None,
            })
            self._evt(t, "write_fail", None, {"cid": cid, "val": val, "reason": "no_primary"})
            return
        primary.value = val
        primary.log.append((primary.epoch, val))
        rep = 1
        for n in self.nodes.values():
            if n.nid == primary.nid or n.role == "crashed":
                continue
            if self._reachable(primary.nid, n.nid):
                n.value = val
                n.log.append((primary.epoch, val))
                rep += 1
        delay = self.rng.uniform(2, 8)
        self.ops_log.append({
            "cid": cid, "op": "write", "arg": val,
            "inv": t, "resp": t + delay, "rval": "ok", "tgt": primary.nid,
        })
        self._evt(t, "write", primary.nid,
                  {"cid": cid, "val": val, "replicated": rep})
        self._snap(t)

    def _h_client_read(self, t, d):
        cid = d["cid"]
        home = cid % self.n_nodes
        primary = self._find_primary_for(home)
        if primary is None:
            self.ops_log.append({
                "cid": cid, "op": "read", "arg": None,
                "inv": t, "resp": None, "rval": None, "tgt": None,
            })
            self._evt(t, "read_fail", None, {"cid": cid, "reason": "no_primary"})
            return
        delay = self.rng.uniform(1, 4)
        self.ops_log.append({
            "cid": cid, "op": "read", "arg": None,
            "inv": t, "resp": t + delay, "rval": primary.value, "tgt": primary.nid,
        })
        self._evt(t, "read", primary.nid, {"cid": cid, "val": primary.value})

    def _h_crash(self, t, d):
        tgt = d["target"]
        for n in self.nodes.values():
            if tgt == "primary" and n.role == "primary":
                n.role = "crashed"
                self._evt(t, "crash", n.nid, {"was": "primary"})
                break
            elif tgt == n.nid or str(tgt) == str(n.nid):
                prev = n.role
                n.role = "crashed"
                self._evt(t, "crash", n.nid, {"was": prev})
                break
        self._elect(t)
        self._snap(t)

    def _h_recover(self, t, d):
        tgt = d["target"]
        for n in self.nodes.values():
            if n.role == "crashed":
                if tgt == "primary" or tgt == n.nid or str(tgt) == str(n.nid):
                    n.role = "secondary"
                    self._evt(t, "recover", n.nid, {})
                    break
        self._snap(t)

    def _h_partition(self, t, d):
        sa, sb = set(d["set_a"]), set(d["set_b"])
        for a in sa:
            for b in sb:
                self.partitions.add((a, b))
                self.partitions.add((b, a))
        self._evt(t, "partition", None, {"set_a": list(sa), "set_b": list(sb)})
        # Check if majority partition needs a new primary
        self._elect_in_partition(t, sb)
        self._snap(t)

    def _h_heal(self, t, d):
        self.partitions.clear()
        self._evt(t, "heal", None, {})
        self._snap(t)

    def save_to_db(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        cur = conn.execute(
            "INSERT INTO runs(seed,config_json,node_count,duration) VALUES(?,?,?,?)",
            (self.seed, json.dumps(self.cfg), self.n_nodes, self.duration),
        )
        rid = cur.lastrowid
        for e in self.events_log:
            conn.execute(
                "INSERT INTO events(run_id,time,type,node_id,details_json) VALUES(?,?,?,?,?)",
                (rid, e["time"], e["type"], e.get("node_id"),
                 json.dumps(e["details"])),
            )
        for o in self.ops_log:
            rv = json.dumps(o["rval"]) if o["rval"] is not None else None
            conn.execute(
                "INSERT INTO operations(run_id,client_id,op_type,arg,invoke_time,"
                "response_time,response_value,target_node) VALUES(?,?,?,?,?,?,?,?)",
                (rid, o["cid"], o["op"], o["arg"], o["inv"],
                 o["resp"], rv, o["tgt"]),
            )
        for s in self.snapshots:
            conn.execute(
                "INSERT INTO node_states(run_id,time,node_id,role,value,epoch,log_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (rid, s["time"], s["node_id"], s["role"], s["value"],
                 s["epoch"], json.dumps(s["log"])),
            )
        conn.commit()
        conn.close()
        return rid


def load_config(path):
    with open(path, "rb") as f:
        if tomllib:
            return tomllib.load(f)
    with open(path, "r") as f:
        content = f.read()
    # minimal TOML parser fallback for simple configs
    import re
    cfg = {}
    current_section = cfg
    current_key = []
    array_mode = False
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[([^\[\]]+)\]$", line)
        if m:
            keys = m.group(1).split(".")
            current_section = cfg
            for k in keys:
                current_section = current_section.setdefault(k, {})
            array_mode = False
            continue
        m = re.match(r"^\[\[([^\[\]]+)\]\]$", line)
        if m:
            keys = m.group(1).split(".")
            parent = cfg
            for k in keys[:-1]:
                parent = parent.setdefault(k, {})
            parent.setdefault(keys[-1], []).append({})
            current_section = parent[keys[-1]][-1]
            array_mode = True
            continue
        m = re.match(r'^(\w+)\s*=\s*(.+)$', line)
        if m:
            k, v = m.group(1), m.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.startswith("[") and v.endswith("]"):
                v = json.loads(v)
            elif "." in v:
                try:
                    v = float(v)
                except ValueError:
                    pass
            else:
                try:
                    v = int(v)
                except ValueError:
                    pass
            current_section[k] = v
    return cfg


def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.close()


def cmd_run(args):
    cfg = load_config(args.config)
    seed = args.seed if args.seed is not None else cfg.get("simulation", {}).get("seed", 0)
    sim = Simulator(cfg, seed)
    sim.run()
    rid = sim.save_to_db(args.db)
    n_ops = len(sim.ops_log)
    n_ev = len(sim.events_log)
    print(f"Run {rid}: seed={seed}, {n_ops} operations, {n_ev} events written to {args.db}")


def cmd_info(args):
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT r.run_id, r.seed, r.node_count, r.duration, r.created_at, "
        "COUNT(DISTINCT o.op_id) AS n_ops, "
        "COUNT(DISTINCT e.event_id) AS n_events "
        "FROM runs r "
        "LEFT JOIN operations o ON o.run_id = r.run_id "
        "LEFT JOIN events e ON e.run_id = r.run_id "
        "GROUP BY r.run_id ORDER BY r.run_id"
    ).fetchall()
    conn.close()
    if not rows:
        print("No runs found.")
        return
    print(f"{'RUN':>4} {'SEED':>6} {'NODES':>5} {'DUR':>7} {'OPS':>5} {'EVENTS':>6}  CREATED")
    print("-" * 70)
    for r in rows:
        print(f"{r['run_id']:>4} {r['seed']:>6} {r['node_count']:>5} "
              f"{r['duration']:>7.0f} {r['n_ops']:>5} {r['n_events']:>6}  {r['created_at']}")


def cmd_trace(args):
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT time, type, node_id, details_json FROM events "
        "WHERE run_id=? ORDER BY time, event_id",
        (args.run_id,),
    ).fetchall()
    conn.close()
    if not rows:
        print(f"No events for run {args.run_id}")
        return
    for r in rows:
        nid = r["node_id"] if r["node_id"] is not None else "-"
        det = r["details_json"] or "{}"
        print(f"  t={r['time']:>8.2f}  {r['type']:<16} node={nid:<3}  {det}")


def cmd_ops(args):
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT op_id, client_id, op_type, arg, invoke_time, response_time, "
        "response_value, target_node FROM operations "
        "WHERE run_id=? ORDER BY invoke_time",
        (args.run_id,),
    ).fetchall()
    conn.close()
    if not rows:
        print(f"No operations for run {args.run_id}")
        return
    print(f"{'OP':>4} {'CLI':>3} {'TYPE':>5} {'ARG':>4} {'INVOKE':>9} "
          f"{'RESPOND':>9} {'RVAL':>6} {'NODE':>4}")
    print("-" * 62)
    for r in rows:
        arg = str(r["arg"]) if r["arg"] is not None else "-"
        resp = f"{r['response_time']:.2f}" if r["response_time"] is not None else "CRASHED"
        rval = r["response_value"] if r["response_value"] is not None else "-"
        tgt = str(r["target_node"]) if r["target_node"] is not None else "-"
        print(f"{r['op_id']:>4} {r['client_id']:>3} {r['op_type']:>5} {arg:>4} "
              f"{r['invoke_time']:>9.2f} {resp:>9} {rval:>6} {tgt:>4}")


def cmd_states(args):
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM node_states WHERE run_id=?"
    params = [args.run_id]
    if args.time is not None:
        q += " AND time=?"
        params.append(args.time)
    q += " ORDER BY time, node_id"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    if not rows:
        print(f"No state snapshots for run {args.run_id}")
        return
    cur_t = None
    for r in rows:
        if r["time"] != cur_t:
            cur_t = r["time"]
            print(f"\n  === t={cur_t:.2f} ===")
        print(f"    node {r['node_id']}: role={r['role']:<10} val={r['value']:<4} "
              f"epoch={r['epoch']}  log={r['log_json']}")


def cmd_query(args):
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(args.sql).fetchall()
    except sqlite3.Error as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        sys.exit(1)
    conn.close()
    if not rows:
        print("(no results)")
        return
    cols = rows[0].keys()
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(r[c]) for c in cols))


def cmd_schema(args):
    print(SCHEMA_SQL)


def cmd_check_config(args):
    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)
    sim = cfg.get("simulation", {})
    print(f"  node_count: {sim.get('node_count', 5)}")
    print(f"  duration: {sim.get('duration', 1000)}")
    print(f"  seed: {sim.get('seed', 0)}")
    clients = cfg.get("clients", {})
    print(f"  clients: {clients.get('count', 3)}")
    print(f"  write_ratio: {clients.get('write_ratio', 0.5)}")
    faults = cfg.get("faults", {}).get("schedule", [])
    print(f"  fault events: {len(faults)}")
    for i, f in enumerate(faults):
        print(f"    [{i}] type={f['type']} time={f['time']}")
    print("Config OK.")


def main():
    p = argparse.ArgumentParser(prog="dessim",
        description="Deterministic Event Simulator for replicated register clusters")
    sp = p.add_subparsers(dest="cmd")

    r = sp.add_parser("run", help="Run a simulation")
    r.add_argument("--config", required=True, help="TOML config file")
    r.add_argument("--db", required=True, help="SQLite database path")
    r.add_argument("--seed", type=int, help="Override seed (default: from config)")

    for name, hlp in [("info", "Show runs summary"), ("trace", "Show event trace"),
                       ("ops", "Show client operations"), ("states", "Show node states")]:
        s = sp.add_parser(name, help=hlp)
        s.add_argument("--db", required=True, help="SQLite database path")
        if name != "info":
            s.add_argument("--run-id", type=int, required=True)
        if name == "states":
            s.add_argument("--time", type=float, default=None)

    q = sp.add_parser("query", help="Run raw SQL")
    q.add_argument("--db", required=True, help="SQLite database path")
    q.add_argument("sql", help="SQL query")

    sp.add_parser("schema", help="Print database schema")

    cc = sp.add_parser("check-config", help="Validate TOML config")
    cc.add_argument("config", help="TOML config file")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)

    fn = {
        "run": cmd_run, "info": cmd_info, "trace": cmd_trace,
        "ops": cmd_ops, "states": cmd_states, "query": cmd_query,
        "schema": cmd_schema, "check-config": cmd_check_config,
    }[args.cmd]
    fn(args)


if __name__ == "__main__":
    main()
