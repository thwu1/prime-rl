#!/usr/bin/env python3
"""
MySQL Split-Brain Binary Log Reconciliation

Parses decoded ROW-format binary log extracts from two data centers,
identifies conflicting writes, resolves them per specified rules,
and produces a reconciled database state.

"""

import json
import re
import pymysql

# Paths
EAST_BINLOG = "/app/binlogs/east_dc.binlog.txt"
WEST_BINLOG = "/app/binlogs/west_dc.binlog.txt"
METADATA_FILE = "/app/metadata.json"
SCHEMA_FILE = "/app/schema.sql"
REPORT_FILE = "/app/reconciliation_report.json"
BASE_DB = "github_meta"
RECONCILED_DB = "github_meta_reconciled"
MYSQL_SOCKET = "/tmp/mysql.sock"


def parse_schema(schema_file):
    """Parse CREATE TABLE statements to extract column ordinal mappings and ENUM defs."""
    with open(schema_file) as f:
        content = f.read()

    # Column map: table_name -> [col1, col2, ...]
    column_map = {}
    # ENUM map: "table.column" -> {1: 'val1', 2: 'val2', ...}
    enum_map = {}

    # Find CREATE TABLE blocks
    table_pattern = re.compile(
        r"CREATE TABLE (\w+)\s*\((.*?)\);", re.DOTALL | re.IGNORECASE
    )
    for match in table_pattern.finditer(content):
        table_name = match.group(1)
        body = match.group(2)
        columns = []
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            # Skip constraints/keys
            if re.match(r"(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN)", line, re.I):
                continue
            # Parse column definition
            col_match = re.match(r"(\w+)\s+(.+)", line)
            if col_match:
                col_name = col_match.group(1)
                col_def = col_match.group(2)
                columns.append(col_name)
                # Check for ENUM
                enum_match = re.search(r"ENUM\(([^)]+)\)", col_def, re.I)
                if enum_match:
                    vals_str = enum_match.group(1)
                    vals = re.findall(r"'([^']*)'", vals_str)
                    enum_map[f"{table_name}.{col_name}"] = {
                        i + 1: v for i, v in enumerate(vals)
                    }
        column_map[table_name] = columns

    return column_map, enum_map


def parse_binlog(filepath, column_map, enum_map):
    """Parse decoded ROW-format binary log to extract DML operations."""
    with open(filepath) as f:
        content = f.read()

    operations = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Detect DML event headers
        dml_match = re.match(
            r"### (UPDATE|INSERT INTO|DELETE FROM) `(\w+)`\.`(\w+)`", line
        )
        if dml_match:
            op_type_raw = dml_match.group(1)
            table = dml_match.group(3)

            if op_type_raw == "INSERT INTO":
                op_type = "INSERT"
            elif op_type_raw == "DELETE FROM":
                op_type = "DELETE"
            else:
                op_type = "UPDATE"

            cols = column_map.get(table, [])
            before = None
            after = None
            section = None
            current_values = {}

            i += 1
            while i < len(lines) and (
                lines[i].startswith("###") or lines[i].strip() == ""
            ):
                stripped = lines[i].lstrip("#").strip()
                if not stripped:
                    i += 1
                    continue

                if stripped == "WHERE":
                    if current_values and section:
                        if section == "WHERE":
                            before = dict(current_values)
                        else:
                            after = dict(current_values)
                    section = "WHERE"
                    current_values = {}
                elif stripped == "SET":
                    if current_values and section:
                        if section == "WHERE":
                            before = dict(current_values)
                        else:
                            after = dict(current_values)
                    section = "SET"
                    current_values = {}
                else:
                    # Parse @N=value /* type info */
                    # Find and remove trailing comment
                    comment_pos = stripped.rfind(" /* ")
                    if comment_pos > 0:
                        value_part = stripped[:comment_pos]
                    else:
                        value_part = stripped

                    col_match = re.match(r"@(\d+)=(.*)", value_part)
                    if col_match:
                        ordinal = int(col_match.group(1))
                        raw_value = col_match.group(2).strip()

                        if ordinal <= len(cols):
                            col_name = cols[ordinal - 1]
                        else:
                            col_name = f"_unknown_{ordinal}"

                        value = _parse_value(raw_value, table, col_name, enum_map)
                        current_values[col_name] = value

                i += 1

            # Capture last section
            if current_values and section:
                if section == "WHERE":
                    before = dict(current_values)
                else:
                    after = dict(current_values)

            # Determine PK
            pk = None
            if after and "id" in after:
                pk = after["id"]
            elif before and "id" in before:
                pk = before["id"]

            operations.append(
                {
                    "type": op_type,
                    "table": table,
                    "before": before,
                    "after": after,
                    "pk": pk,
                }
            )
        else:
            i += 1

    return operations


def _parse_value(raw, table, col_name, enum_map):
    """Parse a raw value from binlog output."""
    if raw == "NULL":
        return None

    # Check ENUM
    enum_key = f"{table}.{col_name}"
    if enum_key in enum_map:
        try:
            ordinal = int(raw)
            return enum_map[enum_key].get(ordinal, raw)
        except ValueError:
            pass

    # Quoted string
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]

    # Integer
    try:
        return int(raw)
    except ValueError:
        pass

    return raw


def find_conflicts(east_ops, west_ops):
    """Find operations that affect the same (table, pk) on both sides."""
    east_by_key = {}
    for op in east_ops:
        key = (op["table"], op["pk"])
        east_by_key[key] = op

    west_by_key = {}
    for op in west_ops:
        key = (op["table"], op["pk"])
        west_by_key[key] = op

    conflicts = []
    for key in east_by_key:
        if key in west_by_key:
            conflicts.append(
                {"key": key, "east": east_by_key[key], "west": west_by_key[key]}
            )

    return conflicts, east_by_key, west_by_key


def resolve_conflicts(conflicts, east_by_key, west_by_key):
    """Resolve each conflict per the metadata rules. Returns resolved operations."""
    resolved = []
    conflict_reports = []

    for conflict in conflicts:
        table, pk = conflict["key"]
        east_op = conflict["east"]
        west_op = conflict["west"]

        if east_op["type"] == "UPDATE" and west_op["type"] == "DELETE":
            # Data preservation: keep UPDATE
            resolved.append(
                {"action": "UPDATE", "table": table, "pk": pk, "data": east_op["after"]}
            )
            conflict_reports.append(
                {
                    "table": table,
                    "primary_key": pk,
                    "east_operation": "UPDATE",
                    "west_operation": "DELETE",
                    "conflict_type": "UPDATE_DELETE",
                    "resolution": "east_preserved_data_integrity",
                    "detail": "East UPDATE preserved over West DELETE per data preservation rule",
                }
            )

        elif east_op["type"] == "DELETE" and west_op["type"] == "UPDATE":
            # Data preservation: keep UPDATE
            resolved.append(
                {"action": "UPDATE", "table": table, "pk": pk, "data": west_op["after"]}
            )
            conflict_reports.append(
                {
                    "table": table,
                    "primary_key": pk,
                    "east_operation": "DELETE",
                    "west_operation": "UPDATE",
                    "conflict_type": "DELETE_UPDATE",
                    "resolution": "west_preserved_data_integrity",
                    "detail": "West UPDATE preserved over East DELETE per data preservation rule",
                }
            )

        elif east_op["type"] == "INSERT" and west_op["type"] == "INSERT":
            # East keeps PK, West gets reassigned (handled later)
            resolved.append(
                {"action": "INSERT", "table": table, "pk": pk, "data": east_op["after"]}
            )
            resolved.append(
                {
                    "action": "INSERT_REASSIGN",
                    "table": table,
                    "original_pk": pk,
                    "data": west_op["after"],
                }
            )
            conflict_reports.append(
                {
                    "table": table,
                    "primary_key": pk,
                    "east_operation": "INSERT",
                    "west_operation": "INSERT",
                    "conflict_type": "INSERT_INSERT",
                    "resolution": "east_keeps_pk_west_reassigned",
                    "detail": f"East INSERT keeps PK {pk}, West INSERT reassigned to next available PK",
                }
            )

        elif east_op["type"] == "UPDATE" and west_op["type"] == "UPDATE":
            if table == "repositories":
                # Special repo rule: MAX for counters
                east_data = east_op["after"]
                west_data = west_op["after"]
                merged = dict(west_data)  # start with west
                merged["stars"] = max(
                    east_data.get("stars", 0), west_data.get("stars", 0)
                )
                merged["forks"] = max(
                    east_data.get("forks", 0), west_data.get("forks", 0)
                )
                # Also compare with base values for forks/stars
                # (in case one side didn't change a counter, use base)
                east_updated = east_data.get("updated_at", "")
                west_updated = west_data.get("updated_at", "")
                merged["updated_at"] = max(east_updated, west_updated)
                resolved.append(
                    {"action": "UPDATE", "table": table, "pk": pk, "data": merged}
                )
                conflict_reports.append(
                    {
                        "table": table,
                        "primary_key": pk,
                        "east_operation": "UPDATE",
                        "west_operation": "UPDATE",
                        "conflict_type": "UPDATE_UPDATE",
                        "resolution": "max_values_merged",
                        "detail": (
                            f"stars=MAX({east_data.get('stars')},{west_data.get('stars')})={merged['stars']}, "
                            f"forks=MAX({east_data.get('forks')},{west_data.get('forks')})={merged['forks']}"
                        ),
                    }
                )
            else:
                # LWW: compare updated_at
                east_ts = east_op["after"].get("updated_at", "")
                west_ts = west_op["after"].get("updated_at", "")
                if west_ts >= east_ts:
                    winner = "west"
                    data = west_op["after"]
                else:
                    winner = "east"
                    data = east_op["after"]
                resolved.append(
                    {"action": "UPDATE", "table": table, "pk": pk, "data": data}
                )
                conflict_reports.append(
                    {
                        "table": table,
                        "primary_key": pk,
                        "east_operation": "UPDATE",
                        "west_operation": "UPDATE",
                        "conflict_type": "UPDATE_UPDATE",
                        "resolution": f"{winner}_wins_lww",
                        "detail": (
                            f"{'West' if winner == 'west' else 'East'} updated_at "
                            f"{west_ts if winner == 'west' else east_ts} > "
                            f"{east_ts if winner == 'west' else west_ts}"
                        ),
                    }
                )

    return resolved, conflict_reports


def create_reconciled_db(conn, resolved_ops, east_ops, west_ops, conflict_keys):
    """Create reconciled database from base + resolved changes."""
    cur = conn.cursor()

    # Create reconciled DB by cloning base
    cur.execute(f"DROP DATABASE IF EXISTS {RECONCILED_DB}")
    cur.execute(f"CREATE DATABASE {RECONCILED_DB}")

    # Clone each table
    for table in ["repositories", "issues"]:
        cur.execute(
            f"CREATE TABLE {RECONCILED_DB}.{table} LIKE {BASE_DB}.{table}"
        )
        cur.execute(
            f"INSERT INTO {RECONCILED_DB}.{table} SELECT * FROM {BASE_DB}.{table}"
        )
    conn.commit()

    cur.execute(f"USE {RECONCILED_DB}")

    # Apply non-conflicting east operations
    for op in east_ops:
        key = (op["table"], op["pk"])
        if key in conflict_keys:
            continue
        _apply_operation(cur, op)

    # Apply non-conflicting west operations
    for op in west_ops:
        key = (op["table"], op["pk"])
        if key in conflict_keys:
            continue
        _apply_operation(cur, op)

    # Apply resolved conflict operations in two passes:
    # Pass 1: INSERT and UPDATE (so East inserts claim their original PKs first)
    for res in resolved_ops:
        table = res["table"]
        if res["action"] == "INSERT":
            _do_insert(cur, table, res["data"])
        elif res["action"] == "UPDATE":
            _do_update(cur, table, res["pk"], res["data"])

    # Pass 2: INSERT_REASSIGN (West inserts get next available PKs after all others)
    for res in resolved_ops:
        if res["action"] != "INSERT_REASSIGN":
            continue
        table = res["table"]
        cur.execute(f"SELECT MAX(id) AS max_id FROM {table}")
        max_id = cur.fetchone()["max_id"] or 0
        new_pk = max_id + 1
        data = dict(res["data"])
        data["id"] = new_pk
        _do_insert(cur, table, data)

    conn.commit()


def _apply_operation(cur, op):
    """Apply a single non-conflicting operation."""
    if op["type"] == "INSERT":
        _do_insert(cur, op["table"], op["after"])
    elif op["type"] == "UPDATE":
        _do_update(cur, op["table"], op["pk"], op["after"])
    elif op["type"] == "DELETE":
        cur.execute(f"DELETE FROM {op['table']} WHERE id = %s", (op["pk"],))


def _do_insert(cur, table, data):
    """Insert a row."""
    cols = list(data.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    values = [data[c] for c in cols]
    cur.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values)


def _do_update(cur, table, pk, data):
    """Update a row by PK."""
    assignments = []
    values = []
    for col, val in data.items():
        if col == "id":
            continue
        assignments.append(f"{col} = %s")
        values.append(val)
    values.append(pk)
    set_clause = ", ".join(assignments)
    cur.execute(f"UPDATE {table} SET {set_clause} WHERE id = %s", values)


def main():
    # Parse schema
    column_map, enum_map = parse_schema(SCHEMA_FILE)
    print(f"Schema parsed: {list(column_map.keys())}")
    print(f"ENUM mappings: {enum_map}")

    # Load metadata
    with open(METADATA_FILE) as f:
        metadata = json.load(f)

    # Parse binlogs
    east_ops = parse_binlog(EAST_BINLOG, column_map, enum_map)
    west_ops = parse_binlog(WEST_BINLOG, column_map, enum_map)
    print(f"East DC operations: {len(east_ops)}")
    print(f"West DC operations: {len(west_ops)}")

    for op in east_ops:
        print(f"  East: {op['type']} {op['table']} pk={op['pk']}")
    for op in west_ops:
        print(f"  West: {op['type']} {op['table']} pk={op['pk']}")

    # Find conflicts
    conflicts, east_by_key, west_by_key = find_conflicts(east_ops, west_ops)
    conflict_keys = {c["key"] for c in conflicts}
    print(f"Conflicts detected: {len(conflicts)}")

    # Resolve conflicts
    resolved_ops, conflict_reports = resolve_conflicts(
        conflicts, east_by_key, west_by_key
    )

    # Update conflict reports with final reassigned PKs (will be filled during DB creation)
    print("Resolved conflicts:")
    for cr in conflict_reports:
        print(f"  {cr['table']} pk={cr['primary_key']}: {cr['resolution']}")

    # Create reconciled database
    conn = pymysql.connect(
        user="root",
        unix_socket=MYSQL_SOCKET,
        cursorclass=pymysql.cursors.DictCursor,
    )
    create_reconciled_db(conn, resolved_ops, east_ops, west_ops, conflict_keys)

    # Verify
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {RECONCILED_DB}.issues")
    print(f"Reconciled issues count: {cur.fetchone()['cnt']}")
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {RECONCILED_DB}.repositories")
    print(f"Reconciled repositories count: {cur.fetchone()['cnt']}")

    conn.close()

    # Write report
    report = {
        "split_brain_window": {
            "start": metadata["incident"]["split_brain_start"],
            "end": metadata["incident"]["split_brain_end"],
        },
        "east_writes_count": len(east_ops),
        "west_writes_count": len(west_ops),
        "total_conflicts": len(conflicts),
        "conflicts": conflict_reports,
    }

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Reconciliation report written to {REPORT_FILE}")
    print("Reconciliation complete.")


if __name__ == "__main__":
    main()
