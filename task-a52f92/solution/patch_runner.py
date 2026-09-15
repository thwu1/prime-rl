#!/usr/bin/env python3
"""
Patch slt_runner.py to add --override CLI flag and integrate the override module.

"""

import sys

def main():
    with open("/app/slt_runner.py") as f:
        code = f.read()

    # 1. Add --override flag to argparse
    old_db_arg = '    parser.add_argument("--db", default=None,'
    new_db_arg = (
        '    parser.add_argument("--override", action="store_true",\n'
        '                        help="Override .slt files with actual output")\n'
        '    parser.add_argument("--db", default=None,'
    )
    code = code.replace(old_db_arg, new_db_arg)

    # 2. Modify main() to handle --override after normal run
    old_main_tail = (
        "    report = runner.get_report(args.file)\n"
        "    print(json.dumps(report))\n"
        "    sys.exit(0 if report[\"failed\"] == 0 else 1)"
    )
    new_main_tail = (
        "    report = runner.get_report(args.file)\n"
        "    print(json.dumps(report))\n"
        "\n"
        "    if getattr(args, 'override', False):\n"
        "        from slt_override import override_file\n"
        "        override_file(args.file, db_path=args.db, labels=args.label)\n"
        "        sys.exit(0)\n"
        "\n"
        "    sys.exit(0 if report[\"failed\"] == 0 else 1)"
    )
    code = code.replace(old_main_tail, new_main_tail)

    with open("/app/slt_runner.py", "w") as f:
        f.write(code)

    print("Patched slt_runner.py with --override support")


if __name__ == "__main__":
    main()
