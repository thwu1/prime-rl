#!/usr/bin/env python3
"""Build programs.db from JSON test program files during Docker build."""

import json
import sqlite3
import glob
import os

DB_PATH = "/app/programs.db"
PROGRAMS_DIR = "/app/_staging"


def create_schema(cur):
    cur.execute("""
    CREATE TABLE programs (
        name TEXT PRIMARY KEY,
        entry_block TEXT NOT NULL,
        phys_regs TEXT NOT NULL,
        num_spill_slots INTEGER NOT NULL DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE blocks (
        program_name TEXT NOT NULL,
        block_id TEXT NOT NULL,
        PRIMARY KEY (program_name, block_id),
        FOREIGN KEY (program_name) REFERENCES programs(name)
    )""")
    cur.execute("""
    CREATE TABLE block_params (
        program_name TEXT NOT NULL,
        block_id TEXT NOT NULL,
        param_idx INTEGER NOT NULL,
        vreg TEXT NOT NULL,
        preg TEXT NOT NULL,
        PRIMARY KEY (program_name, block_id, param_idx),
        FOREIGN KEY (program_name, block_id) REFERENCES blocks(program_name, block_id)
    )""")
    cur.execute("""
    CREATE TABLE instructions (
        program_name TEXT NOT NULL,
        block_id TEXT NOT NULL,
        inst_idx INTEGER NOT NULL,
        kind TEXT NOT NULL,
        detail TEXT NOT NULL,
        PRIMARY KEY (program_name, block_id, inst_idx),
        FOREIGN KEY (program_name, block_id) REFERENCES blocks(program_name, block_id)
    )""")
    cur.execute("""
    CREATE TABLE terminators (
        program_name TEXT NOT NULL,
        block_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        detail TEXT NOT NULL,
        PRIMARY KEY (program_name, block_id),
        FOREIGN KEY (program_name, block_id) REFERENCES blocks(program_name, block_id)
    )""")


def load_program(cur, name, program):
    phys_regs = ",".join(program["phys_regs"])
    cur.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?)",
        (name, program["entry_block"], phys_regs, program.get("num_spill_slots", 0))
    )
    for block_id, block in program["blocks"].items():
        cur.execute(
            "INSERT INTO blocks VALUES (?, ?)",
            (name, block_id)
        )
        for i, param in enumerate(block.get("params", [])):
            cur.execute(
                "INSERT INTO block_params VALUES (?, ?, ?, ?, ?)",
                (name, block_id, i, param["vreg"], param["preg"])
            )
        for i, inst in enumerate(block["instructions"]):
            cur.execute(
                "INSERT INTO instructions VALUES (?, ?, ?, ?, ?)",
                (name, block_id, i, inst["kind"], json.dumps(inst))
            )
        term = block["terminator"]
        cur.execute(
            "INSERT INTO terminators VALUES (?, ?, ?, ?)",
            (name, block_id, term["kind"], json.dumps(term))
        )


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    create_schema(cur)
    for path in sorted(glob.glob(os.path.join(PROGRAMS_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path) as f:
            program = json.load(f)
        load_program(cur, name, program)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
