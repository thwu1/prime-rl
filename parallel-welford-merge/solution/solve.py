"""
Fix all bugs in the parallel statistics pipeline, run it, and generate
the multi-architecture layout design report.
"""


import subprocess
import sys
import json
import math
import os
import importlib


def fix_accumulator():
    """Fix the parallel combine method in accumulator.py."""
    path = '/app/simulator/accumulator.py'

    with open(path, 'r') as f:
        content = f.read()

    # Fix Bug 1: mean - simple average -> weighted mean
    content = content.replace(
        "        combined.mean = (a.mean + b.mean) / 2.0",
        "        combined.mean = (n_a * a.mean + n_b * b.mean) / n"
    )

    # Fix Bug 2: m2 - add n_a*n_b/n scaling
    content = content.replace(
        "        combined.m2 = a.m2 + b.m2 + delta2",
        "        combined.m2 = a.m2 + b.m2 + delta2 * n_a * n_b / n"
    )

    # Fix Bug 3: m3 - add cross-term with m2
    content = content.replace(
        "        # M3: includes third-order cross-term\n"
        "        combined.m3 = (a.m3 + b.m3\n"
        "                       + delta3 * n_a * n_b * (n_a - n_b) / (n * n))",
        "        # M3: includes third-order cross-term and M2 cross-term\n"
        "        combined.m3 = (a.m3 + b.m3\n"
        "                       + delta3 * n_a * n_b * (n_a - n_b) / (n * n)\n"
        "                       + 3.0 * delta * (n_a * b.m2 - n_b * a.m2) / n)"
    )

    # Fix Bug 4: m4 - add all cross-terms
    content = content.replace(
        "        # M4: sum of partial M4s\n"
        "        combined.m4 = a.m4 + b.m4",
        "        # M4: full formula with all cross-terms\n"
        "        combined.m4 = (a.m4 + b.m4\n"
        "                       + delta4 * n_a * n_b * (n_a * n_a - n_a * n_b + n_b * n_b) / (n * n * n)\n"
        "                       + 6.0 * delta2 * (n_a * n_a * b.m2 + n_b * n_b * a.m2) / (n * n)\n"
        "                       + 4.0 * delta * (n_a * b.m3 - n_b * a.m3) / n)"
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed accumulator.py")


def fix_warp():
    """Fix the padding bug in warp.py."""
    path = '/app/simulator/warp.py'

    with open(path, 'r') as f:
        content = f.read()

    # Fix Bug 5: pad with zero accumulators, not copies of first element
    content = content.replace(
        "    # Pad to warp_size with copies of first element\n"
        "    while len(working) < warp_size:\n"
        "        working.append(working[0].copy())",
        "    # Pad to warp_size with zero accumulators (count=0)\n"
        "    while len(working) < warp_size:\n"
        "        working.append(WelfordAccumulator())"
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed warp.py")


def fix_shared_memory():
    """Fix the bank index calculation in shared_memory.py."""
    path = '/app/simulator/shared_memory.py'

    with open(path, 'r') as f:
        content = f.read()

    # Fix Bug 6: word-addressed bank mapping
    content = content.replace(
        "        return byte_address % self.num_banks",
        "        return (byte_address // self.bank_width) % self.num_banks"
    )

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed shared_memory.py")


def run_pipeline():
    """Run the fixed pipeline to generate output."""
    result = subprocess.run(
        ['python3', '/app/parallel_reduce.py'],
        capture_output=True, text=True, cwd='/app'
    )
    print(result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr)
        raise RuntimeError(f"Pipeline failed with exit code {result.returncode}")


def generate_design_report():
    """Generate multi-architecture layout design report."""
    # Invalidate import caches so Python picks up fixed .py files
    importlib.invalidate_caches()
    sys.path.insert(0, '/app')
    from simulator.shared_memory import SharedMemorySimulator

    # Read config with robust fallbacks for all keys
    try:
        with open('/app/config.json', 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}

    target_architectures = config.get('target_architectures', [
        {"name": "gpu_ampere", "num_banks": 32, "bank_width_bytes": 4},
        {"name": "accel_custom", "num_banks": 33, "bank_width_bytes": 4}
    ])

    struct_info = config.get('accumulator_struct', {
        "fields": [
            {"name": "count", "size_bytes": 8},
            {"name": "mean", "size_bytes": 8},
            {"name": "m2", "size_bytes": 8},
            {"name": "m3", "size_bytes": 8},
            {"name": "m4", "size_bytes": 8}
        ],
        "total_size_bytes": 40
    })

    architectures = {}
    for arch in target_architectures:
        architectures[arch['name']] = {
            'sim': SharedMemorySimulator(
                num_banks=arch['num_banks'],
                bank_width_bytes=arch['bank_width_bytes']
            ),
            'num_banks': arch['num_banks']
        }

    field_sizes = [f['size_bytes'] for f in struct_info['fields']]
    base_size = struct_info['total_size_bytes']
    warp_size = config.get('warp_size', 32)

    def compute_aos_conflicts(padding, arch_info):
        sim = arch_info['sim']
        struct_size = base_size + padding
        total = 0
        offset = 0
        for fs in field_sizes:
            analysis = sim.analyze_struct_layout(struct_size, offset, warp_size)
            total += analysis['total_conflicts']
            offset += fs
        return total

    def compute_soa_conflicts(arch_info):
        sim = arch_info['sim']
        total = 0
        for fs in field_sizes:
            addresses = [tid * fs for tid in range(warp_size)]
            total += sim.count_conflicts(addresses)
        return total

    # Evaluate AoS layouts with different padding values
    layouts = []
    for padding in [0, 4, 8, 12, 16, 24]:
        struct_size = base_size + padding
        conflicts = {}
        for arch_name, arch_info in architectures.items():
            conflicts[arch_name] = compute_aos_conflicts(padding, arch_info)

        layouts.append({
            "name": f"aos_{padding}b_padding",
            "padding_bytes": padding,
            "total_struct_size": struct_size,
            "conflicts_by_arch": conflicts,
            "memory_overhead_percent": round(padding / base_size * 100, 2)
        })

    # Evaluate SoA layout
    soa_conflicts = {}
    for arch_name, arch_info in architectures.items():
        soa_conflicts[arch_name] = compute_soa_conflicts(arch_info)

    layouts.append({
        "name": "soa_interleaved",
        "padding_bytes": 0,
        "total_struct_size": base_size,
        "conflicts_by_arch": soa_conflicts,
        "memory_overhead_percent": 0.0
    })

    # Find cross-architecture optimal AoS (0 conflicts on all, minimum overhead)
    aos_layouts = [l for l in layouts if l['name'].startswith('aos_')]
    conflict_free = [l for l in aos_layouts
                     if all(v == 0 for v in l['conflicts_by_arch'].values())]

    if conflict_free:
        optimal = min(conflict_free, key=lambda l: l['memory_overhead_percent'])
    else:
        optimal = min(aos_layouts,
                      key=lambda l: (sum(l['conflicts_by_arch'].values()),
                                     l['memory_overhead_percent']))

    # Ranking: sort by total cross-arch conflicts, then memory overhead
    ranked = sorted(layouts, key=lambda l: (
        sum(l['conflicts_by_arch'].values()),
        l['memory_overhead_percent']
    ))

    # Build justification
    naive = next(l for l in layouts if l['padding_bytes'] == 4)
    accel_arch = next(a for a in target_architectures
                      if a['name'] != 'gpu_ampere')
    naive_accel_conflicts = naive['conflicts_by_arch'][accel_arch['name']]
    opt_stride = optimal['total_struct_size'] // 4

    justification = (
        f"The naive single-architecture solution (4-byte padding, 44-byte struct, "
        f"stride 11 words) eliminates bank conflicts on the 32-bank GPU because "
        f"gcd(11, 32) = 1, making all 32 thread accesses map to distinct banks. "
        f"However, on the {accel_arch['name']} architecture with "
        f"{accel_arch['num_banks']} banks, stride 11 produces "
        f"{naive_accel_conflicts} total conflicts across all fields because "
        f"gcd(11, {accel_arch['num_banks']}) = {math.gcd(11, accel_arch['num_banks'])}, "
        f"mapping all 32 threads to only "
        f"{accel_arch['num_banks'] // math.gcd(11, accel_arch['num_banks'])} banks. "
        f"The minimum cross-architecture solution requires stride {opt_stride} "
        f"({optimal['padding_bytes']} bytes padding, {optimal['total_struct_size']}-byte "
        f"struct) because gcd({opt_stride}, 32) = {math.gcd(opt_stride, 32)} and "
        f"gcd({opt_stride}, {accel_arch['num_banks']}) = "
        f"{math.gcd(opt_stride, accel_arch['num_banks'])}, ensuring all thread accesses "
        f"map to distinct banks on both architectures."
    )

    report = {
        "layouts_evaluated": layouts,
        "cross_arch_optimal": {
            "padding_bytes": optimal['padding_bytes'],
            "padded_struct_size": optimal['total_struct_size'],
            "conflicts_by_arch": optimal['conflicts_by_arch'],
            "memory_overhead_percent": optimal['memory_overhead_percent'],
            "justification": justification
        },
        "ranking": [l['name'] for l in ranked]
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/design_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nDesign report written to /app/output/design_report.json")
    print(f"Layouts evaluated: {len(layouts)}")
    for l in ranked:
        total = sum(l['conflicts_by_arch'].values())
        marker = " <- CROSS-ARCH OPTIMAL" if l['name'] == optimal['name'] else ""
        print(f"  {l['name']}: {total} total conflicts, "
              f"{l['memory_overhead_percent']}% overhead{marker}")


if __name__ == '__main__':
    fix_accumulator()
    fix_warp()
    fix_shared_memory()
    run_pipeline()
    generate_design_report()
    print("\nAll fixes applied, pipeline completed, and design report generated.")
