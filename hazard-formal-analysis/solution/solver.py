#!/usr/bin/env python3
"""
Multi-tool solver for RISC-V Pipeline Hazard Unit EDA analysis.
Orchestrates Verilator (RTL simulation), Yosys (logic synthesis),
and Python (result aggregation and optimization analysis).

"""
import json
import csv
import subprocess
import shutil
from itertools import combinations

INPUT_NAMES = ['BPWrongE', 'CSRWriteFenceM', 'RetM', 'TrapM', 'StructuralStallD',
               'LSUStallM', 'IFUStallF', 'FPUStallD', 'ExternalStall',
               'DivBusyE', 'FDivBusyE', 'wfiM', 'IntPendingM']

STALL_NAMES = ['StallF', 'StallD', 'StallE', 'StallM', 'StallW']
FLUSH_NAMES = ['FlushD', 'FlushE', 'FlushM', 'FlushW']
OUTPUT_NAMES = STALL_NAMES + FLUSH_NAMES

CONFLICT_STAGES = [('StallD', 'FlushD'), ('StallE', 'FlushE'),
                   ('StallM', 'FlushM'), ('StallW', 'FlushW')]


# ==================== Tool Orchestration ====================

def run_verilator():
    """Compile hazard.sv with Verilator and run trace + enumeration."""
    print("=== Verilator: Compiling hazard.sv ===")
    shutil.copy('/solution/testbench.cpp', '/app/testbench.cpp')

    cmd = ['verilator', '--cc', '/app/hazard.sv', '--exe', '/app/testbench.cpp',
           '--build', '-j', '0', '--Mdir', '/app/obj_dir', '-Wno-fatal']
    result = subprocess.run(cmd, capture_output=True, text=True, cwd='/app')
    if result.returncode != 0:
        print(f"Verilator compilation failed:\n{result.stderr}")
        raise RuntimeError("Verilator compilation failed")
    print("Compilation successful")

    print("=== Verilator: Running trace simulation ===")
    result = subprocess.run(['/app/obj_dir/Vhazard', 'trace'],
                            capture_output=True, text=True, cwd='/app')
    if result.returncode != 0:
        raise RuntimeError(f"Trace simulation failed: {result.stderr}")
    print("Trace simulation complete")

    print("=== Verilator: Running exhaustive enumeration ===")
    result = subprocess.run(['/app/obj_dir/Vhazard', 'enumerate'],
                            capture_output=True, text=True, cwd='/app')
    if result.returncode != 0:
        raise RuntimeError(f"Enumeration failed: {result.stderr}")
    print("Enumeration complete (8192 combinations)")


def run_yosys():
    """Run Yosys synthesis to AND/OR/NOT gates."""
    print("\n=== Yosys: Synthesizing to AND/OR/NOT basis gates ===")
    shutil.copy('/solution/synth.ys', '/app/synth.ys')

    result = subprocess.run(['yosys', '-s', '/app/synth.ys'],
                            capture_output=True, text=True, cwd='/app')
    if result.returncode != 0:
        print(f"Yosys synthesis failed:\n{result.stderr}")
        raise RuntimeError("Yosys synthesis failed")
    print("Synthesis complete")


# ==================== Data Parsing ====================

def parse_trace_output():
    rows = []
    with open('/app/trace_output.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: int(v) for k, v in row.items()})
    return rows


def parse_enum_output():
    rows = []
    with open('/app/enum_output.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: int(v) for k, v in row.items()})
    return rows


def parse_trace_input():
    rows = []
    with open('/app/trace.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({name: int(row[name]) for name in INPUT_NAMES})
    return rows


# ==================== Trace Statistics ====================

def compute_trace_stats(trace_output):
    stall_counts = {s: 0 for s in STALL_NAMES}
    flush_counts = {s: 0 for s in FLUSH_NAMES}
    full_stall_streak = 0
    max_streak = 0
    conflict_cycles = 0

    for row in trace_output:
        for s in STALL_NAMES:
            if row[s]:
                stall_counts[s] += 1
        for s in FLUSH_NAMES:
            if row[s]:
                flush_counts[s] += 1

        if all(row[s] for s in STALL_NAMES):
            full_stall_streak += 1
            max_streak = max(max_streak, full_stall_streak)
        else:
            full_stall_streak = 0

        if any(row[s] and row[f] for s, f in CONFLICT_STAGES):
            conflict_cycles += 1

    return stall_counts, flush_counts, max_streak, conflict_cycles


# ==================== Lookup Table & Optimization ====================

def build_lookup(enum_data):
    """Build bits -> outputs lookup table from Verilator enumeration."""
    lookup = {}
    for row in enum_data:
        lookup[row['bits']] = {name: row[name] for name in OUTPUT_NAMES}
    return lookup


def inputs_to_bits(inputs):
    bits = 0
    for i, name in enumerate(INPUT_NAMES):
        if inputs[name]:
            bits |= (1 << i)
    return bits


def compute_critical_input(trace_inputs, lookup):
    baseline = 0
    for inp in trace_inputs:
        out = lookup[inputs_to_bits(inp)]
        baseline += sum(out[s] for s in STALL_NAMES)

    best_reduction = 0
    best_input = None
    for idx, input_name in enumerate(INPUT_NAMES):
        total = 0
        for inp in trace_inputs:
            modified = dict(inp)
            modified[input_name] = 0
            out = lookup[inputs_to_bits(modified)]
            total += sum(out[s] for s in STALL_NAMES)
        reduction = baseline - total
        if reduction > best_reduction:
            best_reduction = reduction
            best_input = input_name

    return best_input


def compute_min_elimination_set(trace_inputs, lookup):
    def has_stalls(zeroed_names):
        for inp in trace_inputs:
            modified = dict(inp)
            for name in zeroed_names:
                modified[name] = 0
            out = lookup[inputs_to_bits(modified)]
            if any(out[s] for s in STALL_NAMES):
                return True
        return False

    for size in range(len(INPUT_NAMES) + 1):
        for combo in combinations(INPUT_NAMES, size):
            if not has_stalls(combo):
                return sorted(list(combo))
    return sorted(INPUT_NAMES)


# ==================== Property Verification ====================

def verify_properties(enum_data):
    results = {}

    def bits_to_input_dict(bits):
        return {name: (bits >> i) & 1 for i, name in enumerate(INPUT_NAMES)}

    def hamming(d):
        return sum(v for v in d.values())

    # P1: Stall monotonicity
    p1_holds = all(
        row['StallF'] >= row['StallD'] >= row['StallE'] >= row['StallM'] >= row['StallW']
        for row in enum_data
    )
    results['P1_stall_monotonicity'] = {'holds': p1_holds, 'counterexample': None}

    # P2: No simultaneous stall and flush
    p2_holds = True
    p2_min_w = 14
    p2_min_ce = None
    for row in enum_data:
        if any(row[s] and row[f] for s, f in CONFLICT_STAGES):
            p2_holds = False
            inp = bits_to_input_dict(row['bits'])
            w = hamming(inp)
            if w < p2_min_w:
                p2_min_w = w
                p2_min_ce = inp
    results['P2_no_simultaneous_stall_flush'] = {
        'holds': p2_holds, 'counterexample': p2_min_ce
    }

    # P3: Trap guarantees flush
    p3_holds = all(
        not ((row['bits'] >> 3) & 1) or (row['FlushD'] and row['FlushE'] and row['FlushM'])
        for row in enum_data
    )
    results['P3_trap_guarantees_flush'] = {'holds': p3_holds, 'counterexample': None}

    # P4: Division protection
    p4_holds = True
    p4_min_w = 14
    p4_min_ce = None
    for row in enum_data:
        inp = bits_to_input_dict(row['bits'])
        if inp['DivBusyE'] and inp['BPWrongE'] and row['FlushE']:
            p4_holds = False
            w = hamming(inp)
            if w < p4_min_w:
                p4_min_w = w
                p4_min_ce = inp
    results['P4_division_protection'] = {
        'holds': p4_holds, 'counterexample': p4_min_ce
    }

    # P5: WFI stall guarantee
    p5_holds = True
    p5_min_w = 14
    p5_min_ce = None
    for row in enum_data:
        inp = bits_to_input_dict(row['bits'])
        if inp['wfiM'] and not inp['IntPendingM'] and not row['StallM']:
            p5_holds = False
            w = hamming(inp)
            if w < p5_min_w:
                p5_min_w = w
                p5_min_ce = inp
    results['P5_wfi_stall_guarantee'] = {
        'holds': p5_holds, 'counterexample': p5_min_ce
    }

    # P6: StallF equals StallD
    p6_holds = all(row['StallF'] == row['StallD'] for row in enum_data)
    results['P6_stallf_equals_stalld'] = {'holds': p6_holds, 'counterexample': None}

    return results


# ==================== Functional Equivalences ====================

def compute_equivalences(enum_data):
    sorted_data = sorted(enum_data, key=lambda r: r['bits'])
    output_vectors = {name: tuple(row[name] for row in sorted_data) for name in OUTPUT_NAMES}

    equivalences = []
    for i in range(len(OUTPUT_NAMES)):
        for j in range(i + 1, len(OUTPUT_NAMES)):
            if output_vectors[OUTPUT_NAMES[i]] == output_vectors[OUTPUT_NAMES[j]]:
                equivalences.append(sorted([OUTPUT_NAMES[i], OUTPUT_NAMES[j]]))
    return equivalences


def compute_unique_outputs(enum_data):
    unique = set()
    for row in enum_data:
        vec = tuple(row[name] for name in OUTPUT_NAMES)
        unique.add(vec)
    return len(unique)


# ==================== Synthesis Metrics ====================

def compute_synthesis_metrics():
    with open('/app/netlist.json', 'r') as f:
        netlist = json.load(f)

    module = netlist['modules']['hazard']
    cells = module['cells']
    ports = module['ports']

    # Cell counts
    total_cells = len(cells)
    cells_by_type = {}
    for cell in cells.values():
        t = cell['type']
        cells_by_type[t] = cells_by_type.get(t, 0) + 1

    # Structural fan-in cone computation via backward BFS
    input_bit_to_name = {}
    for name, port in ports.items():
        if port['direction'] == 'input':
            for bit in port['bits']:
                if isinstance(bit, int):
                    input_bit_to_name[bit] = name

    bit_producer = {}
    cell_input_bits = {}

    for cell_key, cell in cells.items():
        conns = cell['connections']
        dirs = cell.get('port_directions', {})

        for port_name, bits in conns.items():
            direction = dirs.get(port_name, 'output' if port_name == 'Y' else 'input')
            if direction == 'output':
                for bit in bits:
                    if isinstance(bit, int):
                        bit_producer[bit] = cell_key
            else:
                if cell_key not in cell_input_bits:
                    cell_input_bits[cell_key] = set()
                for bit in bits:
                    if isinstance(bit, int):
                        cell_input_bits[cell_key].add(bit)

    output_fan_in = {}
    for name, port in ports.items():
        if port['direction'] == 'output':
            out_bits = [b for b in port['bits'] if isinstance(b, int)]
            visited = set()
            queue = list(out_bits)
            reachable = set()

            while queue:
                bit = queue.pop(0)
                if bit in visited:
                    continue
                visited.add(bit)

                if bit in input_bit_to_name:
                    reachable.add(input_bit_to_name[bit])
                elif bit in bit_producer:
                    ck = bit_producer[bit]
                    for ib in cell_input_bits.get(ck, set()):
                        if ib not in visited:
                            queue.append(ib)

            output_fan_in[name] = sorted(reachable)

    return total_cells, cells_by_type, output_fan_in


# ==================== Main ====================

def main():
    # Step 1: Verilator compilation and simulation
    run_verilator()

    # Step 2: Yosys synthesis
    run_yosys()

    # Step 3: Parse simulation outputs
    print("\n=== Analysis: parsing results ===")
    trace_output = parse_trace_output()
    enum_data = parse_enum_output()
    trace_inputs = parse_trace_input()

    # Trace statistics from Verilator output
    stall_counts, flush_counts, max_streak, conflict_cycles = compute_trace_stats(trace_output)
    print(f"Stall counts: {stall_counts}")
    print(f"Flush counts: {flush_counts}")
    print(f"Max full-stall streak: {max_streak}")
    print(f"Conflict cycles: {conflict_cycles}")

    # Optimization using Verilator enumeration lookup
    lookup = build_lookup(enum_data)
    critical = compute_critical_input(trace_inputs, lookup)
    min_set = compute_min_elimination_set(trace_inputs, lookup)
    print(f"Critical input: {critical}")
    print(f"Min elimination set: {min_set}")

    # Property verification from enumeration
    properties = verify_properties(enum_data)
    for pname, pr in properties.items():
        status = "HOLDS" if pr['holds'] else "FAILS"
        print(f"  {pname}: {status}")

    # Functional equivalences
    equivalences = compute_equivalences(enum_data)
    print(f"Functional equivalences: {equivalences}")

    # Unique output count
    unique_count = compute_unique_outputs(enum_data)
    print(f"Unique output count: {unique_count}")

    # Synthesis metrics from Yosys netlist
    total_cells, cells_by_type, output_fan_in = compute_synthesis_metrics()
    print(f"Total cells: {total_cells}")
    print(f"Cells by type: {cells_by_type}")
    for name, cone in sorted(output_fan_in.items()):
        print(f"  {name} fan-in: {cone}")

    # Assemble results
    results = {
        'properties': properties,
        'trace_analysis': {
            'per_stage_stall_counts': stall_counts,
            'per_stage_flush_counts': flush_counts,
            'longest_full_stall_streak': max_streak,
            'cycles_with_stall_flush_conflict': conflict_cycles,
            'critical_input': critical,
            'minimum_stall_elimination_set': min_set
        },
        'synthesis': {
            'total_cells': total_cells,
            'cells_by_type': cells_by_type,
            'output_fan_in': output_fan_in
        },
        'functional_equivalences': equivalences,
        'unique_output_count': unique_count
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == '__main__':
    main()
