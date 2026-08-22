#!/usr/bin/env python3

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
RING_PATTERN = re.compile(r"Updated consistent hash ring with (\d+) workers")
HEADER_PATTERN = re.compile(r"Found session key in header 'x-session-id': (.+)$")
MAPPING_PATTERN = re.compile(r"Consistent hash routing: key='([^']+)' -> worker='([^']+)'")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit X-Session-ID affinity in a vllm-router debug log."
    )
    parser.add_argument("router_log", type=Path)
    parser.add_argument("--expected-workers", type=int, default=4)
    parser.add_argument("--min-session-ids", type=int, default=1)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.expected_workers < 1:
        raise SystemExit("--expected-workers must be positive")
    if args.min_session_ids < 1:
        raise SystemExit("--min-session-ids must be positive")

    ring_sizes: list[int] = []
    header_session_ids: set[str] = set()
    workers_by_key: dict[str, set[str]] = defaultdict(set)
    mapping_events = 0
    unkeyed_admin_events = 0

    with args.router_log.open(errors="replace") as handle:
        for raw_line in handle:
            line = ANSI_ESCAPE.sub("", raw_line.rstrip())
            if match := RING_PATTERN.search(line):
                ring_sizes.append(int(match.group(1)))
            if match := HEADER_PATTERN.search(line):
                header_session_ids.add(match.group(1))
            if match := MAPPING_PATTERN.search(line):
                key, worker = match.groups()
                workers_by_key[key].add(worker)
                mapping_events += 1
                if key == "request:null":
                    unkeyed_admin_events += 1

    session_workers = {
        key: workers
        for key, workers in workers_by_key.items()
        if key.startswith("header:x-session-id:")
    }
    routed_session_ids = {
        key.removeprefix("header:x-session-id:") for key in session_workers
    }
    missing_mappings = sorted(header_session_ids - routed_session_ids)
    missing_headers = sorted(routed_session_ids - header_session_ids)
    conflicts = {
        key: sorted(workers)
        for key, workers in session_workers.items()
        if len(workers) != 1
    }
    invalid_keys = sorted(
        key
        for key in workers_by_key
        if not key.startswith("header:x-session-id:") and key != "request:null"
    )
    observed_workers = sorted({worker for workers in session_workers.values() for worker in workers})
    issues: list[str] = []
    if not ring_sizes:
        issues.append("no consistent-hash ring update was recorded")
    elif max(ring_sizes) != args.expected_workers:
        issues.append(
            f"largest consistent-hash ring has {max(ring_sizes)} workers, "
            f"expected {args.expected_workers}"
        )
    if len(header_session_ids) < args.min_session_ids:
        issues.append(
            f"found {len(header_session_ids)} X-Session-ID values, "
            f"expected at least {args.min_session_ids}"
        )
    if not session_workers:
        issues.append("no X-Session-ID routing decisions were recorded")
    if invalid_keys:
        issues.append(f"{len(invalid_keys)} routing keys did not use X-Session-ID")
    if missing_mappings:
        issues.append(
            f"{len(missing_mappings)} X-Session-ID values had no routing decision"
        )
    if missing_headers:
        issues.append(
            f"{len(missing_headers)} routed session IDs had no extracted header record"
        )
    if conflicts:
        issues.append(f"{len(conflicts)} session IDs mapped to multiple workers")
    if mapping_events and len(observed_workers) != args.expected_workers:
        issues.append(
            f"routing decisions used {len(observed_workers)} workers, "
            f"expected {args.expected_workers}"
        )

    report = {
        "router_log": str(args.router_log.resolve()),
        "expected_workers": args.expected_workers,
        "ring_sizes": ring_sizes,
        "mapping_events": mapping_events,
        "session_ids": len(session_workers),
        "header_session_ids": len(header_session_ids),
        "unkeyed_admin_events": unkeyed_admin_events,
        "workers": observed_workers,
        "invalid_keys": invalid_keys,
        "missing_mappings": missing_mappings,
        "missing_headers": missing_headers,
        "conflicts": conflicts,
        "issues": issues,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
