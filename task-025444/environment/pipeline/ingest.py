#!/usr/bin/env python3
"""Ingest expected results, tool configurations, and scan findings into SQLite."""

import csv
import json
import os
import sqlite3

import yaml

DB_PATH = "/app/benchmark.db"


def create_schema(conn):
    """Create database tables for pipeline data."""
    conn.executescript("""
        DROP TABLE IF EXISTS expected_results;
        DROP TABLE IF EXISTS findings;
        DROP TABLE IF EXISTS tools;
        DROP TABLE IF EXISTS classifications;
        DROP TABLE IF EXISTS category_metrics;
        DROP TABLE IF EXISTS overall_metrics;

        CREATE TABLE expected_results (
            test_name TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            is_true_positive INTEGER NOT NULL,
            cwe INTEGER NOT NULL
        );

        CREATE TABLE tools (
            name TEXT PRIMARY KEY,
            results_file TEXT NOT NULL,
            commercial INTEGER NOT NULL
        );

        CREATE TABLE findings (
            tool_name TEXT NOT NULL,
            test_name TEXT NOT NULL,
            cwe INTEGER NOT NULL,
            UNIQUE(tool_name, test_name)
        );
    """)


def load_expected_results(conn, filepath):
    """Load expected results CSV into the database."""
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            conn.execute(
                "INSERT INTO expected_results (test_name, category, is_true_positive, cwe) "
                "VALUES (?, ?, ?, ?)",
                (parts[0].strip(), parts[1].strip(),
                 1 if parts[2].strip().lower() == "true" else 0,
                 int(parts[3].strip()))
            )


def load_tool_results(conn, tool_name, filepath):
    """Load a tool's JSONL scan results into the findings table."""
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            conn.execute(
                "INSERT OR REPLACE INTO findings (tool_name, test_name, cwe) "
                "VALUES (?, ?, ?)",
                (tool_name, entry["test_name"], entry["cwe"])
            )


def ingest(config_path):
    """Main ingestion entry point."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    data_dir = os.path.dirname(config_path)

    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)

    expected_path = os.path.join(data_dir, config["expected_results_file"])
    load_expected_results(conn, expected_path)

    for tool in config["tools"]:
        conn.execute(
            "INSERT INTO tools (name, results_file, commercial) VALUES (?, ?, ?)",
            (tool["name"], tool["results_file"], 1 if tool["commercial"] else 0)
        )
        results_path = os.path.join(data_dir, tool["results_file"])
        load_tool_results(conn, tool["name"], results_path)

    conn.commit()
    conn.close()
    print(f"Ingested data into {DB_PATH}")


if __name__ == "__main__":
    ingest("/app/data/config.yaml")
