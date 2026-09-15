#!/usr/bin/env python3
"""CLI for ELF alignment synthesis pipeline."""


import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_test():
    """Run all scenarios and report execution status."""
    from rob_parser import parse_rob_file
    from synth_engine import synthesize_for_section

    obj_dir = '/app/objects'
    print("=" * 64)
    print("  Alignment Synthesis Pipeline - Self Check")
    print("=" * 64)

    ok = 0
    err = 0

    for fname in sorted(os.listdir(obj_dir)):
        if not fname.endswith('.rob'):
            continue
        path = os.path.join(obj_dir, fname)
        try:
            result = parse_rob_file(path)
            for sec in result['sections']:
                _, synth = synthesize_for_section(0, sec, result['arch'])
                desc = ', '.join(f'addend={s.addend}' for s in synth) or 'none'
                print(f"  \033[32mOK\033[0m  {fname}: {sec.name} "
                      f"(align={sec.addralign}) -> synth: {desc}")
                ok += 1
        except Exception as e:
            print(f"  \033[31mERR\033[0m {fname}: {e}")
            err += 1

    print("=" * 64)
    if err == 0:
        print(f"  \033[32mAll {ok} scenarios processed without errors\033[0m")
    else:
        print(f"  {ok} OK, {err} errors")
    return 0 if err == 0 else 1


def cmd_inspect(path):
    """Inspect a parsed .rob file."""
    from rob_parser import parse_rob_file
    result = parse_rob_file(path)
    print(f"Architecture: {result['arch'].name}")
    print(f"Sections ({len(result['sections'])}):")
    for i, sec in enumerate(result['sections']):
        print(f"  [{i}] {sec}")
        for rel in sec.relocations:
            print(f"       {rel}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('test', '-t', '--test'):
        return cmd_test()
    elif sys.argv[1] in ('inspect', '-i') and len(sys.argv) > 2:
        cmd_inspect(sys.argv[2])
        return 0
    else:
        print("Usage:")
        print("  cli.py test              Run all scenarios")
        print("  cli.py inspect FILE.rob  Inspect a parsed .rob file")
        return 1


if __name__ == '__main__':
    sys.exit(main())
