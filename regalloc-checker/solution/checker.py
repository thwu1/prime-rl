#!/usr/bin/env python3
"""
Register allocation verification checker.

Reads program data from SQLite database, verifies register allocation
correctness, outputs JSON verdict and Graphviz DOT visualization.
"""

import json
import os
import sqlite3
import sys

DB_PATH = "/app/programs.db"
OUTPUT_DIR = "/app/output"

# ── Abstract values ──────────────────────────────────────────────────

UNKNOWN = ("unknown",)
CONFLICTED = ("conflicted",)


def make_vreg(name):
    return ("vreg", name)


def val_to_str(val):
    if val == UNKNOWN:
        return "unknown"
    if val == CONFLICTED:
        return "conflicted"
    if isinstance(val, tuple) and val[0] == "vreg":
        return val[1]
    return str(val)


def meet(a, b):
    if a == UNKNOWN:
        return b
    if b == UNKNOWN:
        return a
    if a == b:
        return a
    return CONFLICTED


def meet_states(s1, s2):
    result = {}
    keys = set(s1) | set(s2)
    for k in keys:
        result[k] = meet(s1.get(k, UNKNOWN), s2.get(k, UNKNOWN))
    return result


# ── Load program from SQLite ────────────────────────────────────────

def load_program(program_name):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT * FROM programs WHERE name = ?", (program_name,)
    ).fetchone()
    if row is None:
        print(f"Program '{program_name}' not found in database", file=sys.stderr)
        sys.exit(2)

    phys_regs = row["phys_regs"].split(",")
    entry_block = row["entry_block"]
    num_spill_slots = row["num_spill_slots"]

    block_rows = conn.execute(
        "SELECT block_id FROM blocks WHERE program_name = ?", (program_name,)
    ).fetchall()

    blocks = {}
    for br in block_rows:
        bid = br["block_id"]

        params = []
        param_rows = conn.execute(
            "SELECT vreg, preg FROM block_params "
            "WHERE program_name = ? AND block_id = ? ORDER BY param_idx",
            (program_name, bid)
        ).fetchall()
        for pr in param_rows:
            params.append({"vreg": pr["vreg"], "preg": pr["preg"]})

        instructions = []
        inst_rows = conn.execute(
            "SELECT kind, detail FROM instructions "
            "WHERE program_name = ? AND block_id = ? ORDER BY inst_idx",
            (program_name, bid)
        ).fetchall()
        for ir in inst_rows:
            instructions.append(json.loads(ir["detail"]))

        term_row = conn.execute(
            "SELECT kind, detail FROM terminators "
            "WHERE program_name = ? AND block_id = ?",
            (program_name, bid)
        ).fetchone()
        terminator = json.loads(term_row["detail"])

        blocks[bid] = {
            "params": params,
            "instructions": instructions,
            "terminator": terminator,
        }

    conn.close()

    return {
        "phys_regs": phys_regs,
        "num_spill_slots": num_spill_slots,
        "entry_block": entry_block,
        "blocks": blocks,
    }


# ── Helpers ──────────────────────────────────────────────────────────

def all_locations(program):
    locs = list(program["phys_regs"])
    for i in range(program.get("num_spill_slots", 0)):
        locs.append(f"s{i}")
    return locs


def unknown_state(locations):
    return {loc: UNKNOWN for loc in locations}


def successors(block):
    t = block["terminator"]
    if t["kind"] == "return":
        return []
    if t["kind"] == "jump":
        return [t["target"]]
    if t["kind"] == "branch":
        targets = [t["true_target"]]
        if t["false_target"] != t["true_target"]:
            targets.append(t["false_target"])
        return targets
    return []


def predecessor_map(blocks):
    preds = {bid: set() for bid in blocks}
    for bid, blk in blocks.items():
        for s in successors(blk):
            if s in preds:
                preds[s].add(bid)
    return {bid: list(ps) for bid, ps in preds.items()}


def transfer(state, instructions):
    st = dict(state)
    for inst in instructions:
        k = inst["kind"]
        if k == "op":
            for w in inst.get("writes", []):
                st[w["preg"]] = make_vreg(w["vreg"])
        elif k == "spill":
            st[f"s{inst['dst_slot']}"] = st.get(inst["src_preg"], UNKNOWN)
        elif k == "reload":
            st[inst["dst_preg"]] = st.get(f"s{inst['src_slot']}", UNKNOWN)
        elif k == "move":
            st[inst["dst_preg"]] = st.get(inst["src_preg"], UNKNOWN)
    return st


# ── Core checker ─────────────────────────────────────────────────────

def check_program(program):
    blocks = program["blocks"]
    entry_id = program["entry_block"]
    locs = all_locations(program)
    preds = predecessor_map(blocks)
    unk = unknown_state(locs)

    # Phase 1: fixed-point iteration
    entry_states = {bid: None for bid in blocks}
    exit_states = {bid: dict(unk) for bid in blocks}

    worklist = [entry_id]
    budget = len(blocks) * (len(locs) + 2) + 20

    while worklist and budget > 0:
        budget -= 1
        bid = worklist.pop(0)
        blk = blocks[bid]

        if bid == entry_id:
            merged = dict(unk)
        else:
            pred_list = preds.get(bid, [])
            if not pred_list:
                merged = dict(unk)
            else:
                merged = None
                for p in pred_list:
                    merged = dict(exit_states[p]) if merged is None else meet_states(merged, exit_states[p])

        for param in blk.get("params", []):
            merged[param["preg"]] = make_vreg(param["vreg"])

        if merged == entry_states[bid]:
            continue
        entry_states[bid] = merged
        exit_states[bid] = transfer(merged, blk["instructions"])

        for s in successors(blk):
            if s not in worklist:
                worklist.append(s)

    # Phase 2: verify constraints
    errors = []
    error_blocks = set()

    def check_read(bid, inst_idx, preg, vreg_name, **extra):
        expected = make_vreg(vreg_name)
        actual = state.get(preg, UNKNOWN)
        if actual != expected:
            err = {
                "block": bid,
                "instruction": inst_idx,
                "preg": preg,
                "expected_vreg": vreg_name,
                "actual": val_to_str(actual),
            }
            err.update(extra)
            errors.append(err)
            error_blocks.add(bid)

    for bid, blk in blocks.items():
        es = entry_states[bid]
        if es is None:
            continue
        state = dict(es)

        for i, inst in enumerate(blk["instructions"]):
            k = inst["kind"]
            if k == "op":
                for r in inst.get("reads", []):
                    check_read(bid, i, r["preg"], r["vreg"])
                for w in inst.get("writes", []):
                    state[w["preg"]] = make_vreg(w["vreg"])
            elif k == "spill":
                state[f"s{inst['dst_slot']}"] = state.get(inst["src_preg"], UNKNOWN)
            elif k == "reload":
                state[inst["dst_preg"]] = state.get(f"s{inst['src_slot']}", UNKNOWN)
            elif k == "move":
                state[inst["dst_preg"]] = state.get(inst["src_preg"], UNKNOWN)

        term = blk["terminator"]
        if term["kind"] == "return":
            for r in term.get("reads", []):
                check_read(bid, "terminator", r["preg"], r["vreg"])
        elif term["kind"] == "branch":
            cond = term.get("cond")
            if cond:
                check_read(bid, "terminator", cond["preg"], cond["vreg"])
            for a in term.get("true_args", []):
                check_read(bid, "terminator", a["preg"], a["vreg"])
            for a in term.get("false_args", []):
                check_read(bid, "terminator", a["preg"], a["vreg"])
        elif term["kind"] == "jump":
            for a in term.get("args", []):
                check_read(bid, "terminator", a["preg"], a["vreg"])

    return {"valid": len(errors) == 0, "errors": errors}, error_blocks


# ── DOT output ───────────────────────────────────────────────────────

def generate_dot(program_name, program, error_blocks):
    blocks = program["blocks"]
    lines = [f"digraph {program_name} {{"]
    lines.append("    rankdir=TB;")

    for bid, blk in blocks.items():
        attrs = [f'label="{bid}"']
        if bid in error_blocks:
            attrs.append("style=filled")
            attrs.append("fillcolor=red")
            attrs.append("fontcolor=white")
        lines.append(f"    {bid} [{', '.join(attrs)}];")

    for bid, blk in blocks.items():
        term = blk["terminator"]
        if term["kind"] == "jump":
            lines.append(f"    {bid} -> {term['target']};")
        elif term["kind"] == "branch":
            lines.append(f'    {bid} -> {term["true_target"]} [label="T"];')
            lines.append(f'    {bid} -> {term["false_target"]} [label="F"];')

    lines.append("}")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 2:
        print("Usage: regalloc_checker.py <program_name>", file=sys.stderr)
        sys.exit(2)

    program_name = sys.argv[1]
    program = load_program(program_name)
    result, error_blocks = check_program(program)

    # JSON verdict to stdout
    print(json.dumps(result, indent=2))

    # DOT output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    dot_content = generate_dot(program_name, program, error_blocks)
    dot_path = os.path.join(OUTPUT_DIR, f"{program_name}.dot")
    with open(dot_path, "w") as f:
        f.write(dot_content)

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
