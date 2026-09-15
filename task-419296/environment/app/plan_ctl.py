#!/usr/bin/env python3
"""plan-ctl: TiDB Execution Plan Binary Format Tool.

Reads and analyzes TiDB execution plans stored in .planpb binary format.
The .planpb format is a compact binary serialization of TiDB EXPLAIN ANALYZE
output, used by the diagnostics pipeline for efficient storage and transfer.

Format specification:
  - 4 bytes: magic 'TPLN'
  - 4 bytes: version (uint32 LE)
  - 4 bytes: header length N (uint32 LE)
  - N bytes: gzip-compressed JSON metadata
  - 4 bytes: body length M (uint32 LE)
  - M bytes: gzip-compressed plan text
"""


import argparse
import gzip
import json
import re
import struct
import sys

MAGIC = b'TPLN'
FORMAT_VERSION = 1


def read_planpb(filepath):
    """Read a .planpb file and return (metadata_dict, plan_text_str)."""
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != MAGIC:
            print(
                f"Error: '{filepath}' is not a valid .planpb file "
                f"(expected magic TPLN, got {magic!r})",
                file=sys.stderr,
            )
            sys.exit(1)
        version = struct.unpack('<I', f.read(4))[0]
        if version != FORMAT_VERSION:
            print(
                f"Error: unsupported .planpb version {version} "
                f"(expected {FORMAT_VERSION})",
                file=sys.stderr,
            )
            sys.exit(1)
        hdr_len = struct.unpack('<I', f.read(4))[0]
        hdr_compressed = f.read(hdr_len)
        metadata = json.loads(gzip.decompress(hdr_compressed))
        body_len = struct.unpack('<I', f.read(4))[0]
        body_compressed = f.read(body_len)
        plan_text = gzip.decompress(body_compressed).decode('utf-8')
    return metadata, plan_text


# ─── Execution-info parser ───────────────────────────────────────────

def _tokenize_top_level(s):
    """Split *s* at commas that are NOT inside braces."""
    tokens, depth, buf = [], 0, []
    for c in s:
        if c == '{':
            depth += 1
            buf.append(c)
        elif c == '}':
            depth -= 1
            buf.append(c)
        elif c == ',' and depth == 0:
            t = ''.join(buf).strip()
            if t:
                tokens.append(t)
            buf = []
        else:
            buf.append(c)
    t = ''.join(buf).strip()
    if t:
        tokens.append(t)
    return tokens


def _parse_kv(pair_str):
    """Return (key, value) from 'key:value' or 'key:{…}' strings."""
    depth = 0
    for i, c in enumerate(pair_str):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == ':' and depth == 0:
            key = pair_str[:i].strip()
            val = pair_str[i + 1:].strip()
            if val.startswith('{') and val.endswith('}'):
                return key, _parse_exec_info(val[1:-1])
            return key, val
    return pair_str.strip(), None


def _parse_exec_info(info_str):
    result = {}
    for token in _tokenize_top_level(info_str):
        key, value = _parse_kv(token)
        if key:
            result[key] = value
    return result


# ─── Operator-tree parser ────────────────────────────────────────────

def _parse_operators(plan_text):
    operators = []
    header_seen = False
    for line in plan_text.split('\n'):
        line = line.rstrip()
        if not line.startswith('|'):
            continue
        parts = line.split('|')
        if len(parts) < 10:
            continue
        raw_id = parts[1]
        if raw_id and raw_id[0] == ' ':
            raw_id = raw_id[1:]
        col0 = raw_id.rstrip()
        if col0 == 'id':
            header_seen = True
            continue
        if not header_seen or not col0:
            continue

        i = 0
        while i < len(col0) and not col0[i].isalpha():
            i += 1
        depth = i // 2
        op_id = col0[i:]
        op_id = re.sub(r'\((?:Build|Probe)\)$', '', op_id)

        exec_info_raw = parts[6].strip()

        operators.append({
            'id': op_id,
            'depth': depth,
            'est_rows': parts[2].strip(),
            'act_rows': parts[3].strip(),
            'task': parts[4].strip(),
            'access_object': parts[5].strip(),
            'execution_info': exec_info_raw,
            'operator_info': parts[7].strip() if len(parts) > 7 else '',
        })
    return operators


# ─── Sub-commands ────────────────────────────────────────────────────

def cmd_decode(args):
    """Print the raw EXPLAIN ANALYZE text."""
    _, plan_text = read_planpb(args.file)
    sys.stdout.write(plan_text)


def cmd_metadata(args):
    """Print plan metadata."""
    metadata, _ = read_planpb(args.file)
    if args.json:
        json.dump(metadata, sys.stdout, indent=2)
        print()
    else:
        for k, v in metadata.items():
            print(f'{k}: {v}')


def cmd_operators(args):
    """List operators in the plan."""
    _, plan_text = read_planpb(args.file)
    ops = _parse_operators(plan_text)

    if args.depth is not None:
        ops = [o for o in ops if o['depth'] <= args.depth]

    if args.format == 'json':
        json.dump(ops, sys.stdout, indent=2)
        print()
    elif args.format == 'csv':
        print('id,depth,est_rows,act_rows,task,access_object')
        for o in ops:
            print(f"{o['id']},{o['depth']},{o['est_rows']},"
                  f"{o['act_rows']},{o['task']},{o['access_object']}")
    else:
        hdr = f"{'OPERATOR':<35} {'DEPTH':>5} {'EST':>10} {'ACT':>10} {'TASK':>12}"
        print(hdr)
        print('-' * len(hdr))
        for o in ops:
            prefix = '  ' * o['depth']
            print(f"{prefix + o['id']:<35} {o['depth']:>5} "
                  f"{o['est_rows']:>10} {o['act_rows']:>10} {o['task']:>12}")


def cmd_exec_info(args):
    """Extract execution info for a single operator."""
    _, plan_text = read_planpb(args.file)
    ops = _parse_operators(plan_text)

    target = None
    for o in ops:
        if o['id'] == args.operator:
            target = o
            break
    if target is None:
        print(f"Error: operator '{args.operator}' not found in plan.",
              file=sys.stderr)
        print('Available operators:', file=sys.stderr)
        for o in ops:
            print(f'  {o["id"]}', file=sys.stderr)
        sys.exit(1)

    parsed = _parse_exec_info(target['execution_info'])

    if args.key:
        if args.key not in parsed:
            print(f"Error: key '{args.key}' not in execution info.",
                  file=sys.stderr)
            print('Available keys: ' + ', '.join(parsed.keys()),
                  file=sys.stderr)
            sys.exit(1)
        val = parsed[args.key]
        if isinstance(val, dict):
            json.dump(val, sys.stdout, indent=2)
            print()
        else:
            print(val)
    else:
        json.dump(parsed, sys.stdout, indent=2)
        print()


def cmd_compare(args):
    """Compare two plans side-by-side."""
    m1, t1 = read_planpb(args.file1)
    m2, t2 = read_planpb(args.file2)
    ops1 = _parse_operators(t1)
    ops2 = _parse_operators(t2)

    ids1 = {o['id']: o for o in ops1}
    ids2 = {o['id']: o for o in ops2}
    common = sorted(set(ids1) & set(ids2))
    only1 = sorted(set(ids1) - set(ids2))
    only2 = sorted(set(ids2) - set(ids1))

    result = {
        'plan1': {'file': args.file1, 'query': m1.get('query', ''),
                  'operators': len(ops1)},
        'plan2': {'file': args.file2, 'query': m2.get('query', ''),
                  'operators': len(ops2)},
        'common_operators': common,
        'only_in_plan1': only1,
        'only_in_plan2': only2,
    }

    if args.format == 'json':
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"Plan 1: {len(ops1)} operators  ({m1.get('query', 'N/A')[:60]})")
        print(f"Plan 2: {len(ops2)} operators  ({m2.get('query', 'N/A')[:60]})")
        print(f'Common: {len(common)}   Only-1: {len(only1)}   Only-2: {len(only2)}')
        if only1:
            print(f'  plan-1 unique: {", ".join(only1)}')
        if only2:
            print(f'  plan-2 unique: {", ".join(only2)}')


# ─── CLI entry-point ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='plan-ctl',
        description=(
            'TiDB Execution Plan Binary Format Tool.\n'
            'Read and analyze .planpb files produced by the TiDB diagnostics '
            'pipeline.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Use "plan-ctl <command> -h" for command-specific help.',
    )
    sub = parser.add_subparsers(dest='command', help='available commands')

    # decode
    p = sub.add_parser('decode',
                       help='Decode .planpb to human-readable EXPLAIN ANALYZE')
    p.add_argument('file', help='.planpb file path')

    # metadata
    p = sub.add_parser('metadata',
                       help='Show plan metadata (query, timing, digest)')
    p.add_argument('file', help='.planpb file path')
    p.add_argument('--json', action='store_true',
                   help='Output as JSON (default: key-value lines)')

    # operators
    p = sub.add_parser('operators', help='List operators in the plan')
    p.add_argument('file', help='.planpb file path')
    p.add_argument('--format', choices=['text', 'json', 'csv'],
                   default='text', help='Output format (default: text)')
    p.add_argument('--depth', type=int, default=None,
                   help='Maximum operator depth to include')

    # exec-info
    p = sub.add_parser('exec-info',
                       help='Extract parsed execution info for one operator')
    p.add_argument('file', help='.planpb file path')
    p.add_argument('operator',
                   help='Operator ID, e.g. Point_Get_1 or IndexLookUp_10')
    p.add_argument('--key', default=None,
                   help='Return only this top-level key from execution info')

    # compare
    p = sub.add_parser('compare', help='Compare two plans')
    p.add_argument('file1', help='First .planpb file')
    p.add_argument('file2', help='Second .planpb file')
    p.add_argument('--format', choices=['text', 'json'], default='text')

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        'decode': cmd_decode,
        'metadata': cmd_metadata,
        'operators': cmd_operators,
        'exec-info': cmd_exec_info,
        'compare': cmd_compare,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
