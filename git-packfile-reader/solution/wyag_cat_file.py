#!/usr/bin/env python3

"""
wyag-cat-file — CLI tool for reading Git objects via gitlib.

Usage:
    wyag-cat-file -t <sha> [--repo <path>]
    wyag-cat-file -p <sha> [--repo <path>]
"""

import sys
import os
import argparse

sys.path.insert(0, '/app')
import gitlib


def type_from_mode(mode_str):
    """Infer the object type from a tree entry's mode (matches git's logic)."""
    mode_int = int(mode_str, 8)
    if mode_int == 0o160000:
        return 'commit'
    elif mode_int & 0o040000:
        return 'tree'
    else:
        return 'blob'


def pretty_print_tree(repo, obj):
    """Pretty-print a tree object matching git cat-file -p format."""
    output = []
    for item in obj.items:
        mode_raw = item.mode.decode() if isinstance(item.mode, bytes) else str(item.mode)
        mode_display = mode_raw.zfill(6)
        entry_type = type_from_mode(mode_raw)
        output.append(f"{mode_display} {entry_type} {item.sha}\t{item.path}\n")
    return ''.join(output).encode()


def main():
    parser = argparse.ArgumentParser(
        description='Read Git objects using gitlib'
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('-t', action='store_true', help='Show object type')
    mode.add_argument('-p', action='store_true', help='Pretty-print object content')
    parser.add_argument('sha', help='Object SHA-1 identifier')
    parser.add_argument('--repo', default='/app/repo', help='Repository path')

    args = parser.parse_args()

    try:
        repo = gitlib.GitRepository(args.repo)
        obj = gitlib.object_read(repo, args.sha)
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        sys.exit(1)

    if args.t:
        sys.stdout.buffer.write(obj.fmt.decode().encode() + b'\n')
    elif args.p:
        if obj.fmt == b'tree':
            sys.stdout.buffer.write(pretty_print_tree(repo, obj))
        else:
            sys.stdout.buffer.write(obj.serialize())


if __name__ == '__main__':
    main()
