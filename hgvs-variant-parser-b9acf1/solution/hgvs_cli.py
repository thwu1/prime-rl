#!/usr/bin/env python3
"""HGVS CLI tool — parse, classify, validate, batch-process, and database operations."""

import sys
import json
import argparse
import csv
import sqlite3

sys.path.insert(0, "/app")
from hgvs_parser import parse, format_variant, roundtrip, classify_edit, validate_grammar


def cmd_parse(args):
    results = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        v = parse(line)
        results.append({
            "input": line,
            "accession": v.ac,
            "gene": v.gene,
            "type": v.type,
            "edit_type": classify_edit(line),
        })
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_classify(args):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        t = classify_edit(line)
        sys.stdout.write(f"{line}\t{t}\n")


def cmd_validate(args):
    rule = args.rule
    results = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        valid = validate_grammar(rule, line)
        results.append({"input": line, "valid": valid})
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_batch(args):
    filepath = args.file
    results = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rid = row["id"]
            op = row["operation"]
            inp = row["input"]
            if op == "roundtrip":
                result = roundtrip(inp)
            elif op == "classify":
                result = classify_edit(inp)
            elif op.startswith("validate:"):
                rule = op.split(":", 1)[1]
                result = validate_grammar(rule, inp)
            else:
                result = None
            results.append({"id": rid, "result": result})
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_db_load(args):
    conn = sqlite3.connect(args.db)
    conn.execute("DROP TABLE IF EXISTS variants")
    conn.execute("""CREATE TABLE variants (
        accession TEXT,
        gene TEXT,
        type TEXT,
        edit_type TEXT,
        raw TEXT,
        formatted TEXT
    )""")
    with open(args.file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            v = parse(line)
            formatted = format_variant(v)
            et = classify_edit(line)
            conn.execute(
                "INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?)",
                (v.ac, v.gene, v.type, et, line, formatted)
            )
    conn.commit()
    conn.close()


def cmd_db_query(args):
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(args.sql)
    results = [dict(row) for row in cursor.fetchall()]
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")
    conn.close()


def main():
    parser = argparse.ArgumentParser(prog="hgvs-tool")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("parse", help="Parse HGVS strings from stdin to JSON")
    sub.add_parser("classify", help="Classify edit types from stdin to TSV")

    val = sub.add_parser("validate", help="Validate strings against grammar rule")
    val.add_argument("--rule", required=True)

    bat = sub.add_parser("batch", help="Process batch TSV file")
    bat.add_argument("file")

    db_parser = sub.add_parser("db", help="Database operations")
    db_sub = db_parser.add_subparsers(dest="db_command", required=True)

    load_parser = db_sub.add_parser("load", help="Load variants into SQLite")
    load_parser.add_argument("file")
    load_parser.add_argument("--db", required=True)

    query_parser = db_sub.add_parser("query", help="Query SQLite database")
    query_parser.add_argument("--db", required=True)
    query_parser.add_argument("--sql", required=True)

    args = parser.parse_args()

    if args.command == "parse":
        cmd_parse(args)
    elif args.command == "classify":
        cmd_classify(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "db":
        if args.db_command == "load":
            cmd_db_load(args)
        elif args.db_command == "query":
            cmd_db_query(args)


if __name__ == "__main__":
    main()
