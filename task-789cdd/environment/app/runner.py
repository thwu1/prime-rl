#!/usr/bin/env python3
"""
CCS Clinical Simulation Runner

Reads a session transcript file and runs it through the simulation engine,
then scores the result.

Usage: python3 runner.py <transcript_file>

Transcript format (one command per line):
    ORDER <free text order>
    ADVANCE <minutes>
    LOCATION <location_name>
    # comment lines are ignored
"""
import json
import sys

from order_matcher import OrderMatcher
from simulation import SimulationEngine
from scorer import Scorer


def load_json(path):
    with open(path) as f:
        return json.load(f)


def parse_transcript_file(filepath):
    """Parse a text-based transcript file into action list."""
    actions = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "ORDER":
                actions.append(("order", arg))
            elif cmd == "ADVANCE":
                actions.append(("advance", int(arg)))
            elif cmd == "LOCATION":
                actions.append(("location", arg))
            else:
                print(f"Unknown command: {line}", file=sys.stderr)
    return actions


def run_case(case_path, catalog_path, rubric_path, transcript_path):
    case = load_json(case_path)
    catalog = load_json(catalog_path)
    rubric = load_json(rubric_path)

    engine = SimulationEngine(case, catalog)
    scorer_obj = Scorer(rubric)

    actions = parse_transcript_file(transcript_path)

    print("=" * 60)
    print("CCS Clinical Simulation - Case Runner")
    print("=" * 60)
    print(f"\nCase: {case.get('title', 'Unknown')}")
    print(f"Initial Location: {engine.get_state()['location']}")
    print()

    for action_type, arg in actions:
        if action_type == "order":
            result = engine.place_order(arg)
            status = result["status"]
            if status == "accepted":
                print(
                    f"[t={engine.get_state()['current_time']:3d}] "
                    f"ORDER: {arg} -> {result['canonical_name']} "
                    f"(report at t={result['report_time']})"
                )
            else:
                print(
                    f"[t={engine.get_state()['current_time']:3d}] "
                    f"ORDER: {arg} -> REJECTED: {result['message']}"
                )

        elif action_type == "advance":
            result = engine.advance_clock(arg)
            print(f"\n--- Clock advanced to t={result['new_time']} ---")
            if result["events_fired"]:
                for e in result["events_fired"]:
                    print(f"  EVENT: {e}")
            if result["results_available"]:
                for r in result["results_available"]:
                    print(f"  RESULT: {r}")
            print()

        elif action_type == "location":
            result = engine.change_location(arg)
            print(
                f"[t={engine.get_state()['current_time']:3d}] "
                f"LOCATION: {arg} -> {result['status']}"
            )

    # Score the case
    transcript = engine.get_transcript()
    score_result = scorer_obj.score(transcript)

    print("\n" + "=" * 60)
    print("SCORING REPORT")
    print("=" * 60)
    print(
        f"\nTotal Score: {score_result['total_score']:.1f} / "
        f"{rubric.get('max_score', 100)}"
    )

    print("\nAction Details:")
    for detail in score_result["item_details"]:
        print(
            f"  {detail['action']:40s} "
            f"{detail['credit']:5.1f} / {detail['max_credit']:5.1f}  "
            f"({detail['reason']})"
        )

    if score_result["penalties"]:
        print("\nPenalties:")
        for pen in score_result["penalties"]:
            print(
                f"  {pen['action']:40s} "
                f"-{pen['penalty']:5.1f}  ({pen['reason']})"
            )

    return score_result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 runner.py <transcript_file>")
        print(
            "       Files case.json, catalog.json, rubric.json "
            "expected in /data/ directory."
        )
        sys.exit(1)

    run_case("/data/case.json", "/data/catalog.json", "/data/rubric.json", sys.argv[1])
