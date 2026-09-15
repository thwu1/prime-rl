#!/usr/bin/env python3
"""EAMxx configuration query/change CLI tool."""

import argparse
import json
import sys
import os

sys.path.insert(0, "/app")


def run_check(xml_path, ref_path):
    from resolver import NamelistResolver

    with open(ref_path) as f:
        ref = json.load(f)

    case_env = ref["case_env"]
    expected = ref["expected"]
    resolver = NamelistResolver(xml_path, case_env)

    failures = 0
    for param in sorted(expected.keys()):
        exp_val = expected[param]
        try:
            actual = resolver.get(param)
            match = False
            if isinstance(exp_val, float) and isinstance(actual, float):
                match = abs(actual - exp_val) < max(1.0, abs(exp_val) * 1e-9)
            elif isinstance(exp_val, list) and isinstance(actual, list):
                match = exp_val == actual
            else:
                match = actual == exp_val
            if not match:
                print(f"  MISMATCH  {param}")
                print(f"    expected: {exp_val!r}")
                print(f"    actual:   {actual!r}")
                failures += 1
            else:
                print(f"  OK        {param}")
        except Exception as e:
            print(f"  ERROR     {param}: {e}")
            failures += 1

    print()
    if failures == 0:
        print(f"ALL {len(expected)} CHECKS PASSED")
    else:
        print(f"{failures}/{len(expected)} CHECKS FAILED")
    return failures


def main():
    parser = argparse.ArgumentParser(
        description="EAMxx configuration query/change tool")
    parser.add_argument("--xml", default="/app/namelist_defaults.xml",
                        help="Path to namelist defaults XML")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", metavar="REF_JSON",
                       help="Validate resolver against reference JSON")
    group.add_argument("--case", metavar="CASE_JSON",
                       help="Case environment JSON for interactive mode")

    parser.add_argument("--yaml", action="store_true",
                        help="Output resolved parameters as YAML")
    parser.add_argument("--get", metavar="PARAM",
                        help="Get a parameter value")
    parser.add_argument("--set", nargs=2, metavar=("PARAM", "VALUE"),
                        help="Set a parameter value")
    parser.add_argument("--query", metavar="PATTERN",
                        help="Query parameters matching regex")
    parser.add_argument("--list", nargs="?", const="", metavar="GROUP",
                        help="List parameters, optionally under a group")
    parser.add_argument("--metadata", metavar="PARAM",
                        help="Show parameter metadata as JSON")
    args = parser.parse_args()

    if args.check:
        failures = run_check(args.xml, args.check)
        sys.exit(1 if failures else 0)

    if not args.case:
        parser.error("--case or --check is required")

    from resolver import NamelistResolver

    with open(args.case) as f:
        case_env = json.load(f)

    resolver = NamelistResolver(args.xml, case_env)

    if args.yaml:
        print(resolver.to_yaml())
    elif args.get:
        val = resolver.get(args.get)
        print(repr(val))
    elif args.set:
        resolver.set(args.set[0], args.set[1])
        print(f"Set {args.set[0]} = {resolver.get(args.set[0])!r}")
    elif args.query:
        for p in resolver.query(args.query):
            print(f"  {p} = {resolver.get(p)!r}")
    elif args.list is not None:
        for p in resolver.list_params(args.list):
            print(p)
    elif args.metadata:
        meta = resolver.get_metadata(args.metadata)
        print(json.dumps(meta, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
