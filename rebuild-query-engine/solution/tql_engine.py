#!/usr/bin/env python3
"""TQL Engine — reference implementation using sqlite3 as backend."""

import sqlite3
import sys
import os
import csv


DATA_DIR = os.environ.get("TQL_DATA_DIR", "/data")


def is_int(s):
    """Check whether a string represents an integer."""
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False


def is_numeric(s):
    """Check whether a string represents any number (int or float)."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def infer_column_types(headers, rows):
    """Infer INTEGER / REAL / TEXT for each column from data values."""
    col_types = []
    for i in range(len(headers)):
        non_null = []
        for row in rows:
            if i < len(row):
                v = row[i].strip()
                if v.upper() != "NULL" and v != "":
                    non_null.append(v)
        if not non_null:
            col_types.append("TEXT")
        elif all(is_int(v) for v in non_null):
            col_types.append("INTEGER")
        elif all(is_numeric(v) for v in non_null):
            col_types.append("REAL")
        else:
            col_types.append("TEXT")
    return col_types


def load_tsv(conn, filepath, table_name):
    """Load a TSV file into an sqlite3 table with type inference."""
    with open(filepath, "r", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        headers = next(reader)
        rows = list(reader)

    col_types = infer_column_types(headers, rows)

    col_defs = ", ".join(
        '"{}" {}'.format(h, t) for h, t in zip(headers, col_types)
    )
    conn.execute('CREATE TABLE "{}" ({})'.format(table_name, col_defs))

    placeholders = ", ".join(["?"] * len(headers))
    for row in rows:
        values = []
        for i in range(len(headers)):
            v = row[i] if i < len(row) else ""
            if v.upper() == "NULL":
                values.append(None)
            elif col_types[i] == "INTEGER":
                try:
                    values.append(int(v))
                except ValueError:
                    values.append(v)
            elif col_types[i] == "REAL":
                try:
                    values.append(float(v))
                except ValueError:
                    values.append(v)
            else:
                values.append(v)
        conn.execute(
            'INSERT INTO "{}" VALUES ({})'.format(table_name, placeholders),
            values,
        )


# ---------------------------------------------------------------------------
# Custom MEDIAN aggregate
# ---------------------------------------------------------------------------

class _MedianAgg:
    def __init__(self):
        self.vals = []

    def step(self, value):
        if value is not None:
            self.vals.append(float(value))

    def finalize(self):
        if not self.vals:
            return None
        self.vals.sort()
        n = len(self.vals)
        if n % 2 == 1:
            med = self.vals[n // 2]
        else:
            med = (self.vals[n // 2 - 1] + self.vals[n // 2]) / 2.0
        if med == int(med):
            return int(med)
        return med


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _fmt(value):
    """Format a single result cell for TSV output."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: tql <query>", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]

    conn = sqlite3.connect(":memory:")
    conn.create_aggregate("MEDIAN", 1, _MedianAgg)
    conn.execute("PRAGMA case_sensitive_like = ON")

    # Load every .tsv file in the data directory as a table.
    if os.path.isdir(DATA_DIR):
        for fname in sorted(os.listdir(DATA_DIR)):
            if fname.endswith(".tsv"):
                tbl = fname[:-4]
                load_tsv(conn, os.path.join(DATA_DIR, fname), tbl)

    conn.commit()

    try:
        cursor = conn.execute(query)
    except sqlite3.Error as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    if cursor.description:
        headers = [d[0] for d in cursor.description]
        print("\t".join(headers))
        for row in cursor:
            print("\t".join(_fmt(v) for v in row))

    conn.close()


if __name__ == "__main__":
    main()
