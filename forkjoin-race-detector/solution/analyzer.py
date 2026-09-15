#!/usr/bin/env python3
"""
Fork-Join Parallel Program Analyzer — Reference Implementation

Builds a computation DAG from async-finish program descriptions with
phaser synchronization, computes work, span, ideal parallelism, detects
data races, and generates Graphviz DOT output.
"""
import json
import sys
import os
from collections import defaultdict, deque


class DAGBuilder:
    """Builds a computation DAG from a JSON program description."""

    def __init__(self, phasers_spec):
        self.nodes = {}
        self.syn_ctr = 0
        self.finish_async_lasts = defaultdict(list)
        self.phasers = (
            {p["id"]: p["registered"] for p in phasers_spec}
            if phasers_spec
            else {}
        )
        self.phase_counters = defaultdict(
            lambda: defaultdict(lambda: {"sig": 0, "wait": 0})
        )
        self.phase_signals = defaultdict(list)
        self.phase_waits = defaultdict(list)
        self.edge_types = {}

    def _syn(self, tag):
        self.syn_ctr += 1
        nid = f"__{tag}_{self.syn_ctr}"
        self.nodes[nid] = {
            "cost": 0,
            "access": None,
            "succs": [],
            "preds": [],
            "op_type": "synthetic",
            "label": tag,
        }
        return nid

    def _node(self, nid, cost, access=None, op_type="compute", label=""):
        self.nodes[nid] = {
            "cost": cost,
            "access": access,
            "succs": [],
            "preds": [],
            "op_type": op_type,
            "label": label,
        }

    def _edge(self, u, v, etype="continuation"):
        self.nodes[u]["succs"].append(v)
        self.nodes[v]["preds"].append(u)
        self.edge_types[(u, v)] = etype

    def build(self, program):
        entry = self._syn("start")
        last = self._body(program["body"], entry, "__root__", "MAIN")
        self._add_phaser_edges()
        return entry, last

    def _body(self, body, prev, fscope, task_name):
        for item in body:
            op = item["op"]
            if op == "compute":
                nid = item["id"]
                self._node(
                    nid, item["cost"],
                    op_type="compute",
                    label=f"compute({item['cost']})",
                )
                if prev is not None:
                    self._edge(prev, nid)
                prev = nid
            elif op in ("read", "write"):
                nid = item["id"]
                self._node(
                    nid, 1,
                    access=(op, item["var"]),
                    op_type=op,
                    label=f"{op}({item['var']})",
                )
                if prev is not None:
                    self._edge(prev, nid)
                prev = nid
            elif op == "signal":
                nid = item["id"]
                ph_id = item["phaser"]
                phase = self.phase_counters[task_name][ph_id]["sig"]
                self._node(nid, 0, op_type="signal", label=f"signal({ph_id})")
                if prev is not None:
                    self._edge(prev, nid)
                prev = nid
                self.phase_signals[(ph_id, phase)].append(nid)
                self.phase_counters[task_name][ph_id]["sig"] += 1
            elif op == "wait":
                nid = item["id"]
                ph_id = item["phaser"]
                phase = self.phase_counters[task_name][ph_id]["wait"]
                self._node(nid, 0, op_type="wait", label=f"wait({ph_id})")
                if prev is not None:
                    self._edge(prev, nid)
                prev = nid
                self.phase_waits[(ph_id, phase)].append(nid)
                self.phase_counters[task_name][ph_id]["wait"] += 1
            elif op == "next":
                sig_nid = item["id"] + "_sig"
                wait_nid = item["id"] + "_wait"
                ph_id = item["phaser"]
                sig_phase = self.phase_counters[task_name][ph_id]["sig"]
                wait_phase = self.phase_counters[task_name][ph_id]["wait"]
                self._node(sig_nid, 0, op_type="signal", label=f"signal({ph_id})")
                self._node(wait_nid, 0, op_type="wait", label=f"wait({ph_id})")
                if prev is not None:
                    self._edge(prev, sig_nid)
                self._edge(sig_nid, wait_nid)
                prev = wait_nid
                self.phase_signals[(ph_id, sig_phase)].append(sig_nid)
                self.phase_waits[(ph_id, wait_phase)].append(wait_nid)
                self.phase_counters[task_name][ph_id]["sig"] += 1
                self.phase_counters[task_name][ph_id]["wait"] += 1
            elif op == "async":
                ae = self._syn(f"ae_{item['task']}")
                if prev is not None:
                    self._edge(prev, ae, etype="spawn")
                clast = self._body(item["body"], ae, fscope, item["task"])
                if clast is None:
                    clast = ae
                self.finish_async_lasts[fscope].append(clast)
            elif op == "finish":
                fid = item["id"]
                blst = self._body(item["body"], prev, fid, task_name)
                jn = self._syn(f"jn_{fid}")
                if blst is not None:
                    self._edge(blst, jn, etype="join")
                for al in self.finish_async_lasts.pop(fid, []):
                    self._edge(al, jn, etype="join")
                prev = jn
        return prev

    def _add_phaser_edges(self):
        all_keys = set(self.phase_signals.keys()) | set(self.phase_waits.keys())
        for key in all_keys:
            for sig_node in self.phase_signals.get(key, []):
                for wait_node in self.phase_waits.get(key, []):
                    self._edge(sig_node, wait_node, etype="phaser")


def compute_work(nodes):
    return sum(n["cost"] for n in nodes.values())


def compute_span(nodes, entry, sink):
    dist = {nid: float("-inf") for nid in nodes}
    dist[entry] = nodes[entry]["cost"]
    indeg = {nid: len(n["preds"]) for nid, n in nodes.items()}
    q = deque(nid for nid, d in indeg.items() if d == 0)
    while q:
        u = q.popleft()
        for v in nodes[u]["succs"]:
            c = dist[u] + nodes[v]["cost"]
            if c > dist[v]:
                dist[v] = c
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return dist[sink]


def detect_races(nodes):
    accesses = [
        (nid, n["access"][0], n["access"][1])
        for nid, n in nodes.items()
        if n["access"] is not None
    ]

    indeg = {nid: len(n["preds"]) for nid, n in nodes.items()}
    topo = []
    q = deque(nid for nid, d in indeg.items() if d == 0)
    while q:
        u = q.popleft()
        topo.append(u)
        for v in nodes[u]["succs"]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    ancestors = {nid: set() for nid in nodes}
    for u in topo:
        for p in nodes[u]["preds"]:
            ancestors[u].add(p)
            ancestors[u] |= ancestors[p]

    races = []
    for i in range(len(accesses)):
        for j in range(i + 1, len(accesses)):
            id1, t1, v1 = accesses[i]
            id2, t2, v2 = accesses[j]
            if v1 != v2:
                continue
            if t1 == "read" and t2 == "read":
                continue
            if id1 not in ancestors[id2] and id2 not in ancestors[id1]:
                a, b = sorted([id1, id2])
                races.append({"access1": a, "access2": b, "variable": v1})

    seen = set()
    unique = []
    for r in races:
        k = (r["access1"], r["access2"], r["variable"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    unique.sort(key=lambda r: (r["variable"], r["access1"], r["access2"]))
    return unique


def generate_dot(name, nodes, edge_types):
    lines = [f"digraph {name} {{", "    rankdir=TB;"]

    for nid, n in nodes.items():
        shape = "box"
        if n["op_type"] == "synthetic":
            shape = "ellipse"
        elif n["op_type"] in ("signal", "wait"):
            shape = "diamond"
        lbl = n.get("label", nid) or nid
        display = f"{nid}\\n{lbl}" if lbl != nid else nid
        lines.append(f'    "{nid}" [label="{display}" shape={shape}];')

    for (u, v), etype in edge_types.items():
        style = "solid"
        color = "black"
        if etype == "spawn":
            style = "dashed"
        elif etype == "join":
            style = "dotted"
        elif etype == "phaser":
            style = "bold"
            color = "red"
        lines.append(f'    "{u}" -> "{v}" [style={style} color={color}];')

    lines.append("}")
    return "\n".join(lines)


def analyze(program_path):
    with open(program_path) as f:
        program = json.load(f)

    phasers_spec = program.get("phasers", [])
    builder = DAGBuilder(phasers_spec)
    entry, sink = builder.build(program)
    nodes = builder.nodes

    work = compute_work(nodes)
    span = compute_span(nodes, entry, sink)
    par = round(work / span, 4) if span > 0 else float("inf")
    races = detect_races(nodes)

    dot = generate_dot(program["name"], nodes, builder.edge_types)
    os.makedirs("/app/graphs", exist_ok=True)
    with open(f"/app/graphs/{program['name']}.dot", "w") as f:
        f.write(dot)

    return {
        "name": program["name"],
        "work": work,
        "span": span,
        "ideal_parallelism": par,
        "data_races": races,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyzer.py <program.json> ...")
        sys.exit(1)
    os.makedirs("/app/results", exist_ok=True)
    for p in sys.argv[1:]:
        r = analyze(p)
        out = f"/app/results/{r['name']}.json"
        with open(out, "w") as f:
            json.dump(r, f, indent=2)
        print(
            f"{r['name']}: work={r['work']} span={r['span']} "
            f"par={r['ideal_parallelism']} races={len(r['data_races'])}"
        )


if __name__ == "__main__":
    main()
