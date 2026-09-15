#!/usr/bin/env python3
"""Configuration management tool - FIXED with semantic validation for rules field."""

import json
import sys
import sqlite3

DB_PATH = "/app/data/config.db"


def validate_config(config_json):
    """Validate a quota policy configuration before pushing."""
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    required_fields = ["name", "rules"]
    for field in required_fields:
        if field not in config:
            return False, f"Missing required field: {field}"

    if not isinstance(config.get("name"), str):
        return False, "Field 'name' must be a string"

    if len(config["name"]) == 0:
        return False, "Field 'name' must not be empty"

    # Validate that rules is a list of objects
    rules = config.get("rules")
    if not isinstance(rules, list):
        return False, f"Field 'rules' must be a list, got {type(rules).__name__}"

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            return False, f"Rule at index {i} must be an object, got {type(rule).__name__}"

    return True, "Valid"


def push_config(config_json):
    """Push a new quota policy to the database."""
    config = json.loads(config_json) if isinstance(config_json, str) else config_json

    valid, msg = validate_config(config)
    if not valid:
        print(f"Error: {msg}", file=sys.stderr)
        return False

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO quota_policies (name, rules, enforce_mode, path_prefix, active) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            config["name"],
            json.dumps(config.get("rules")),
            config.get("enforce_mode", "enforce"),
            config.get("path_prefix", "*"),
            1
        )
    )
    conn.execute(
        "INSERT INTO config_versions (config_json, pushed_by, status) VALUES (?, ?, ?)",
        (json.dumps(config), "config_pusher", "active")
    )
    conn.commit()
    conn.close()
    print(f"Successfully pushed config: {config['name']}")
    return True


def main():
    if "--validate" in sys.argv:
        idx = sys.argv.index("--validate")
        if idx + 1 < len(sys.argv):
            config_json = sys.argv[idx + 1]
        else:
            config_json = sys.stdin.read()
        valid, msg = validate_config(config_json)
        if valid:
            print("Config is valid")
        else:
            print(f"Config is invalid: {msg}", file=sys.stderr)
            sys.exit(1)
    elif "--push" in sys.argv:
        idx = sys.argv.index("--push")
        if idx + 1 < len(sys.argv):
            config_json = sys.argv[idx + 1]
        else:
            config_json = sys.stdin.read()
        if not push_config(config_json):
            sys.exit(1)
    else:
        print("Usage: config_pusher.py [--validate|--push] <config_json>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
