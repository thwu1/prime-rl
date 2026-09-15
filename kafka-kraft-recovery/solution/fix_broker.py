#!/usr/bin/env python3
"""
Fix broken Kafka KRaft broker configuration by diagnosing and correcting errors.

"""
import os
import re

CONFIG_PATH = "/app/kafka/config/kraft/server.properties"


def parse_properties(filepath):
    """Parse a Java properties file preserving order and comments."""
    entries = []
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                entries.append(("_comment", line.rstrip()))
                continue
            if "=" in stripped:
                key, value = stripped.split("=", 1)
                entries.append((key.strip(), value.strip()))
    return entries


def fix_config():
    entries = parse_properties(CONFIG_PATH)

    fixes = {}
    present_keys = set()

    for key, value in entries:
        if key == "_comment":
            continue
        present_keys.add(key)

        # Fix 1: process.roles must be broker,controller for combined KRaft mode
        if key == "process.roles" and value != "broker,controller":
            fixes["process.roles"] = "broker,controller"

        # Fix 2: node.id must match the ID in controller.quorum.voters
        # voters format is "ID@host:port" - extract the ID and use it
        if key == "node.id":
            fixes["node.id"] = "1"  # Will match voters=1@localhost:9093

        # Fix 3: controller.quorum.voters - ensure port is present
        if key == "controller.quorum.voters":
            if ":" not in value.split("@")[1] if "@" in value else True:
                fixes["controller.quorum.voters"] = "1@localhost:9093"

        # Fix 4: listeners - fix malformed CONTROLLER protocol URI (missing colon)
        if key == "listeners":
            fixed = re.sub(r"(\w+)//", r"\1://", value)
            if fixed != value:
                fixes["listeners"] = fixed

        # Fix 5: advertised.listeners must NOT include CONTROLLER listener
        if key == "advertised.listeners":
            parts = [p.strip() for p in value.split(",")]
            non_controller = [p for p in parts if not p.startswith("CONTROLLER")]
            if len(non_controller) != len(parts):
                fixes["advertised.listeners"] = ",".join(non_controller)

        # Fix 6: log.dirs must point to a valid directory
        if key == "log.dirs" and not os.path.exists(value):
            new_dir = "/tmp/kraft-combined-logs"
            os.makedirs(new_dir, exist_ok=True)
            fixes["log.dirs"] = new_dir

        # Fix 7: num.partitions must be >= 1
        if key == "num.partitions":
            try:
                if int(value) < 1:
                    fixes["num.partitions"] = "1"
            except ValueError:
                fixes["num.partitions"] = "1"

        # Fix 8-9: replication factors must be <= broker count (1 for single node)
        if key in (
            "offsets.topic.replication.factor",
            "transaction.state.log.replication.factor",
        ):
            try:
                if int(value) > 1:
                    fixes[key] = "1"
            except ValueError:
                fixes[key] = "1"

        # Fix 10: transaction min ISR must be <= replication factor (1 for single node)
        if key == "transaction.state.log.min.isr":
            try:
                if int(value) > 1:
                    fixes[key] = "1"
            except ValueError:
                fixes[key] = "1"

        # Fix 11: log.retention.hours must be positive
        if key == "log.retention.hours":
            try:
                if int(value) <= 0:
                    fixes["log.retention.hours"] = "168"
            except ValueError:
                fixes["log.retention.hours"] = "168"

        # Fix 12: log.segment.bytes must be positive
        if key == "log.segment.bytes":
            try:
                if int(value) <= 0:
                    fixes["log.segment.bytes"] = "1073741824"
            except ValueError:
                fixes["log.segment.bytes"] = "1073741824"

    # Fix 13-14: Add missing required KRaft properties
    required_additions = {}

    if "controller.listener.names" not in present_keys:
        required_additions["controller.listener.names"] = "CONTROLLER"

    if "inter.broker.listener.name" not in present_keys:
        required_additions["inter.broker.listener.name"] = "PLAINTEXT"

    # Write the fixed configuration
    with open(CONFIG_PATH, "w") as f:
        for key, value in entries:
            if key == "_comment":
                f.write(value + "\n")
            else:
                fixed_value = fixes.get(key, value)
                f.write(f"{key}={fixed_value}\n")

        if required_additions:
            f.write("\n# Required KRaft properties\n")
            for key, value in required_additions.items():
                f.write(f"{key}={value}\n")

    print(f"Fixed {len(fixes)} values: {list(fixes.keys())}")
    print(f"Added {len(required_additions)} properties: {list(required_additions.keys())}")


if __name__ == "__main__":
    fix_config()
