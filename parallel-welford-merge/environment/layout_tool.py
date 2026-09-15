#!/usr/bin/env python3
"""
GPU Shared Memory Layout Analysis Tool

Evaluates struct memory layout strategies for bank conflict optimization.
Supports array-of-structs (AoS) and struct-of-arrays (SoA) layouts.
Uses the shared memory simulator from /app/simulator/.
"""


import argparse
import json
import sys
import os

sys.path.insert(0, '/app')
from simulator.shared_memory import SharedMemorySimulator


def cmd_analyze(args):
    """Analyze a single AoS layout."""
    sim = SharedMemorySimulator(num_banks=args.banks, bank_width_bytes=args.bank_width)
    field_sizes = [int(x) for x in args.field_sizes.split(',')]
    base_size = sum(field_sizes)
    struct_size = base_size + args.padding

    field_offsets = []
    offset = 0
    for fs in field_sizes:
        field_offsets.append(offset)
        offset += fs

    field_results = []
    total_conflicts = 0
    for i, (fo, fs) in enumerate(zip(field_offsets, field_sizes)):
        analysis = sim.analyze_struct_layout(struct_size, fo, args.threads)
        field_results.append({
            'index': i,
            'offset': fo,
            'size': fs,
            'conflicts': analysis['total_conflicts'],
            'unique_banks': analysis['unique_banks']
        })
        total_conflicts += analysis['total_conflicts']

    avg_util = (sum(f['unique_banks'] for f in field_results)
                / (len(field_results) * args.banks)) if field_results else 0

    result = {
        'layout': 'AoS',
        'base_struct_size': base_size,
        'padding_bytes': args.padding,
        'total_struct_size': struct_size,
        'total_conflicts': total_conflicts,
        'conflict_free': total_conflicts == 0,
        'avg_bank_utilization': round(avg_util, 4),
        'memory_overhead_percent': round(args.padding / base_size * 100, 2) if base_size > 0 else 0,
        'fields': field_results
    }

    if args.format == 'json':
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"AoS Layout Analysis")
        print(f"  Struct: {base_size}B + {args.padding}B padding = {struct_size}B")
        print(f"  Total conflicts: {total_conflicts}")
        print(f"  Conflict-free: {result['conflict_free']}")
        print(f"  Memory overhead: {result['memory_overhead_percent']}%")
        print(f"  Avg bank utilization: {avg_util:.1%}")
        for f in field_results:
            print(f"    Field {f['index']}: offset={f['offset']}, conflicts={f['conflicts']}, "
                  f"banks={f['unique_banks']}/{args.banks}")


def cmd_sweep(args):
    """Sweep padding values for AoS layouts."""
    sim = SharedMemorySimulator(num_banks=args.banks, bank_width_bytes=args.bank_width)
    field_sizes = [int(x) for x in args.field_sizes.split(',')]
    base_size = sum(field_sizes)

    field_offsets = []
    offset = 0
    for fs in field_sizes:
        field_offsets.append(offset)
        offset += fs

    results = []
    optimal = None

    for padding in range(0, args.max_padding + 1, args.step):
        struct_size = base_size + padding
        total_conflicts = 0
        for fo in field_offsets:
            analysis = sim.analyze_struct_layout(struct_size, fo, args.threads)
            total_conflicts += analysis['total_conflicts']

        entry = {
            'padding_bytes': padding,
            'total_struct_size': struct_size,
            'total_conflicts': total_conflicts,
            'conflict_free': total_conflicts == 0,
            'memory_overhead_percent': round(padding / base_size * 100, 2) if base_size > 0 else 0
        }
        results.append(entry)

        if optimal is None and total_conflicts == 0:
            optimal = entry

    sweep_result = {
        'base_struct_size': base_size,
        'field_sizes': field_sizes,
        'sweep_range': f"0-{args.max_padding} step {args.step}",
        'results': results,
        'optimal': optimal
    }

    if args.format == 'json':
        json.dump(sweep_result, sys.stdout, indent=2)
        print()
    else:
        print(f"Padding Sweep (base={base_size}B, step={args.step})")
        print(f"  {'Pad':>4}  {'Size':>5}  {'Conflicts':>9}  {'Overhead':>8}  Status")
        print(f"  {'-'*50}")
        for r in results:
            status = "OPTIMAL" if r == optimal else ("ok" if r['conflict_free'] else "")
            print(f"  {r['padding_bytes']:>4}  {r['total_struct_size']:>5}  "
                  f"{r['total_conflicts']:>9}  {r['memory_overhead_percent']:>7.1f}%  {status}")


def cmd_soa(args):
    """Analyze struct-of-arrays layout."""
    sim = SharedMemorySimulator(num_banks=args.banks, bank_width_bytes=args.bank_width)
    field_sizes = [int(x) for x in args.field_sizes.split(',')]
    base_size = sum(field_sizes)

    field_results = []
    total_conflicts = 0
    total_memory = 0

    for i, fs in enumerate(field_sizes):
        addresses = [tid * fs for tid in range(args.threads)]
        conflicts = sim.count_conflicts(addresses)
        banks_used = len(set(sim.get_bank(a) for a in addresses))

        field_results.append({
            'index': i,
            'element_size': fs,
            'conflicts': conflicts,
            'unique_banks': banks_used
        })
        total_conflicts += conflicts
        total_memory += fs * args.threads

    avg_util = (sum(f['unique_banks'] for f in field_results)
                / (len(field_results) * args.banks)) if field_results else 0

    result = {
        'layout': 'SoA',
        'base_struct_size': base_size,
        'total_conflicts': total_conflicts,
        'conflict_free': total_conflicts == 0,
        'total_memory_per_warp': total_memory,
        'avg_bank_utilization': round(avg_util, 4),
        'fields': field_results
    }

    if args.format == 'json':
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(f"SoA Layout Analysis")
        print(f"  Base struct size: {base_size}B")
        print(f"  Total conflicts: {total_conflicts}")
        print(f"  Conflict-free: {result['conflict_free']}")
        print(f"  Total memory/warp: {total_memory}B")
        print(f"  Avg bank utilization: {avg_util:.1%}")
        for f in field_results:
            print(f"    Field {f['index']}: elem_size={f['element_size']}B, "
                  f"conflicts={f['conflicts']}, banks={f['unique_banks']}/{args.banks}")


def cmd_compare(args):
    """Compare layouts from a JSON definition file."""
    with open(args.layouts, 'r') as f:
        layout_defs = json.load(f)

    sim = SharedMemorySimulator(num_banks=args.banks, bank_width_bytes=args.bank_width)

    results = []
    for ldef in layout_defs:
        name = ldef.get('name', f'layout_{len(results)}')
        field_sizes = ldef['field_sizes']
        base_size = sum(field_sizes)
        is_soa = ldef.get('interleave', False)
        padding = ldef.get('padding', 0)

        if is_soa:
            total_conflicts = 0
            for fs in field_sizes:
                addresses = [tid * fs for tid in range(args.threads)]
                total_conflicts += sim.count_conflicts(addresses)
            struct_size = base_size
            memory = sum(fs * args.threads for fs in field_sizes)
        else:
            struct_size = base_size + padding
            total_conflicts = 0
            offset = 0
            for fs in field_sizes:
                analysis = sim.analyze_struct_layout(struct_size, offset, args.threads)
                total_conflicts += analysis['total_conflicts']
                offset += fs
            memory = struct_size * args.threads

        results.append({
            'name': name,
            'layout_type': 'SoA' if is_soa else 'AoS',
            'padding_bytes': 0 if is_soa else padding,
            'total_struct_size': struct_size,
            'total_conflicts': total_conflicts,
            'conflict_free': total_conflicts == 0,
            'memory_per_warp': memory,
            'memory_overhead_percent': round(padding / base_size * 100, 2) if (base_size > 0 and not is_soa) else 0
        })

    ranked = sorted(results, key=lambda r: (
        0 if r['conflict_free'] else 1,
        r['total_conflicts'],
        r['memory_per_warp']
    ))

    comparison = {
        'layouts': results,
        'ranking': [r['name'] for r in ranked],
        'best': ranked[0]['name'] if ranked else None,
        'summary': {
            'total_evaluated': len(results),
            'conflict_free_count': sum(1 for r in results if r['conflict_free'])
        }
    }

    if args.format == 'json':
        json.dump(comparison, sys.stdout, indent=2)
        print()
    else:
        print(f"Layout Comparison ({len(results)} layouts)")
        print(f"  {'Rank':>4}  {'Name':<20}  {'Type':<4}  {'Pad':>3}  "
              f"{'Conflicts':>9}  {'Memory':>6}  {'Overhead':>8}")
        print(f"  {'-'*68}")
        for i, r in enumerate(ranked):
            print(f"  {i+1:>4}  {r['name']:<20}  {r['layout_type']:<4}  "
                  f"{r['padding_bytes']:>3}  {r['total_conflicts']:>9}  "
                  f"{r['memory_per_warp']:>6}  {r['memory_overhead_percent']:>7.1f}%")
        print(f"\n  Best: {comparison['best']}")


def main():
    parser = argparse.ArgumentParser(
        description='GPU Shared Memory Layout Analysis Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    def add_common_args(p):
        p.add_argument('--banks', type=int, default=32,
                        help='Number of memory banks (default: 32)')
        p.add_argument('--bank-width', type=int, default=4,
                        help='Bank width in bytes (default: 4)')
        p.add_argument('--threads', type=int, default=32,
                        help='Threads per warp (default: 32)')
        p.add_argument('--format', choices=['text', 'json'], default='text',
                        help='Output format (default: text)')

    # analyze subcommand
    p_analyze = subparsers.add_parser('analyze',
                                       help='Analyze a single AoS layout')
    p_analyze.add_argument('--field-sizes', required=True,
                            help='Comma-separated field sizes in bytes (e.g., 8,8,8,8,8)')
    p_analyze.add_argument('--padding', type=int, default=0,
                            help='Padding bytes to append to struct')
    add_common_args(p_analyze)

    # sweep subcommand
    p_sweep = subparsers.add_parser('sweep',
                                     help='Sweep AoS padding values')
    p_sweep.add_argument('--field-sizes', required=True,
                          help='Comma-separated field sizes in bytes')
    p_sweep.add_argument('--max-padding', type=int, default=32,
                          help='Maximum padding to test (default: 32)')
    p_sweep.add_argument('--step', type=int, default=1,
                          help='Padding step size (default: 1)')
    add_common_args(p_sweep)

    # soa subcommand
    p_soa = subparsers.add_parser('soa',
                                   help='Analyze struct-of-arrays layout')
    p_soa.add_argument('--field-sizes', required=True,
                        help='Comma-separated field sizes in bytes')
    add_common_args(p_soa)

    # compare subcommand
    p_compare = subparsers.add_parser('compare',
                                       help='Compare layouts from JSON definition file')
    p_compare.add_argument('--layouts', required=True,
                            help='Path to JSON file defining layouts to compare')
    add_common_args(p_compare)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        'analyze': cmd_analyze,
        'sweep': cmd_sweep,
        'soa': cmd_soa,
        'compare': cmd_compare
    }
    commands[args.command](args)


if __name__ == '__main__':
    main()
