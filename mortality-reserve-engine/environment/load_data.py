#!/usr/bin/env python3
"""Load SOA XTbML XML data into SQLite mortality database.

Parses mortality tables (select-and-ultimate) and improvement scales
from XTbML format and inserts into the normalized database schema.
"""

import argparse
import os
import sqlite3
import xml.etree.ElementTree as ET


def parse_and_load_xml(xml_path, conn):
    """Parse an XTbML file and load its data into the database."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Extract metadata from ContentClassification
    cc = root.find("ContentClassification")
    table_id = int(cc.find("TableIdentity").text.strip())
    ct_elem = cc.find("ContentType")
    content_type = ct_elem.text.strip() if ct_elem.text else ""
    table_name = cc.find("TableName").text.strip()
    desc_elem = cc.find("TableDescription")
    description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

    conn.execute(
        "INSERT OR REPLACE INTO table_metadata VALUES (?, ?, ?, ?, ?)",
        (table_id, content_type, table_name, description, os.path.basename(xml_path))
    )

    tables = root.findall("Table")

    if len(tables) >= 2:
        # Select-and-ultimate table (e.g., VBT 2015, CSO 2017)
        _load_select_table(conn, table_id, tables[0])
        _load_ultimate_table(conn, table_id, tables[1])
    elif len(tables) == 1:
        # Single table: could be 2D improvement scale or 1D aggregate
        meta = tables[0].find("MetaData")
        axis_defs = meta.findall("AxisDef")
        if len(axis_defs) == 2:
            _load_improvement_scale(conn, table_id, tables[0])
        else:
            _load_ultimate_table(conn, table_id, tables[0])


def _load_select_table(conn, table_id, table_elem):
    """Load select mortality rates from a two-dimensional table element."""
    for age_axis in table_elem.findall("Values/Axis"):
        age = int(age_axis.attrib["t"])
        inner = age_axis.find("Axis")
        if inner is None:
            continue
        for y in inner.findall("Y"):
            dur = int(y.attrib["t"])
            qx = float(y.text)
            conn.execute(
                "INSERT INTO select_rates VALUES (?, ?, ?, ?)",
                (table_id, age, dur, qx)
            )


def _load_ultimate_table(conn, table_id, table_elem):
    """Load ultimate or aggregate mortality rates."""
    # Handle both nested-Axis and flat-Axis structures
    y_elems = table_elem.findall("Values/Axis/Y")
    if not y_elems:
        # Try nested structure: Values/Axis/Axis/Y
        y_elems = table_elem.findall("Values/Axis/Axis/Y")
    for y in y_elems:
        age = int(y.attrib["t"])
        qx = float(y.text)
        conn.execute(
            "INSERT OR REPLACE INTO ultimate_rates VALUES (?, ?, ?)",
            (table_id, age, qx)
        )


def _load_improvement_scale(conn, table_id, table_elem):
    """Load two-dimensional improvement scale (age x year)."""
    for age_axis in table_elem.findall("Values/Axis"):
        age = int(age_axis.attrib["t"])
        # Read year/rate pairs from this age group
        for y in age_axis.findall("Y"):
            year = int(y.attrib["t"])
            rate = float(y.text)
            conn.execute(
                "INSERT OR REPLACE INTO improvement_factors VALUES (?, ?, ?, ?)",
                (table_id, age, year, rate)
            )


def main():
    parser = argparse.ArgumentParser(description="Load XTbML data into SQLite")
    parser.add_argument("--db", required=True, help="Path to SQLite database")
    parser.add_argument("--data-dir", required=True, help="Directory with XML files")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    loaded = 0
    for fname in sorted(os.listdir(args.data_dir)):
        if not fname.endswith(".xml"):
            continue
        path = os.path.join(args.data_dir, fname)
        try:
            parse_and_load_xml(path, conn)
            loaded += 1
            print(f"  Loaded: {fname}")
        except Exception as e:
            print(f"  Error loading {fname}: {e}")

    conn.commit()
    conn.close()
    print(f"=== Loaded {loaded} table files ===")


if __name__ == "__main__":
    main()
