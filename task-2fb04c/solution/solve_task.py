#!/usr/bin/env python3
"""
Solution: Parse binary hardware traces, evaluate emulator conformance,
create conformance report, and fix the emulator.

"""

import json
import struct
import subprocess
import sys
import importlib

sys.path.insert(0, '/app')

TRACES_PATH = '/app/traces.bin'
REPORT_PATH = '/app/conformance_report.json'
EMULATOR_PATH = '/app/cpu8088.py'
REG_ORDER = ['ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di']


def parse_traces():
    """Parse the binary trace file, including the undocumented flags mask."""
    with open(TRACES_PATH, 'rb') as f:
        data = f.read()

    # Header: 4-byte magic + 2-byte version + 2-byte count
    magic = data[:4]
    assert magic == b'8T88', f"Unexpected magic: {magic!r}"
    version, count = struct.unpack('<HH', data[4:8])
    print(f"Trace file: version={version}, {count} records")

    # Determine record size empirically
    payload = len(data) - 8
    record_size = payload // count
    assert record_size * count == payload, "Records don't divide evenly"
    print(f"Record size: {record_size} bytes (format doc says 81, documents 79)")

    # The undocumented 2 bytes at offsets 79-80 are the per-instruction
    # FLAGS comparison mask — needed because the 8088 leaves certain flag
    # bits undefined for specific instruction classes.

    traces = []
    offset = 8
    for _ in range(count):
        rec = data[offset:offset + record_size]

        name = rec[:32].rstrip(b'\x00').decode('ascii')
        insn_len = rec[32]
        insn_bytes = list(rec[33:33 + insn_len])

        init_regs = list(struct.unpack('<8H', rec[41:57]))
        init_flags = struct.unpack('<H', rec[57:59])[0]
        init_ip = struct.unpack('<H', rec[59:61])[0]

        exp_regs = list(struct.unpack('<8H', rec[61:77]))
        exp_flags = struct.unpack('<H', rec[77:79])[0]

        # Undocumented: flags comparison mask
        flags_mask = struct.unpack('<H', rec[79:81])[0]

        traces.append({
            'name': name,
            'bytes': insn_bytes,
            'initial': dict(zip(REG_ORDER, init_regs), flags=init_flags, ip=init_ip),
            'expected': dict(zip(REG_ORDER, exp_regs), flags=exp_flags),
            'flags_mask': flags_mask,
        })
        offset += record_size

    return traces


def decode_instruction(insn_bytes):
    """Use ndisasm to decode raw instruction bytes into assembly."""
    result = subprocess.run(
        ['ndisasm', '-b', '16', '-'],
        input=bytes(insn_bytes),
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        line = result.stdout.decode('ascii', errors='replace').strip().split('\n')[0]
        parts = line.split(None, 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return f"db {','.join(f'0x{b:02x}' for b in insn_bytes)}"


def categorize_instruction(name, decoded):
    """Classify an instruction into a failure analysis category."""
    mnemonic = decoded.split()[0].lower()
    if mnemonic in ('daa', 'das'):
        return 'bcd_adjustment'
    elif mnemonic in ('aam', 'aad'):
        return 'ascii_arithmetic'
    elif mnemonic in ('shl', 'shr', 'sal', 'sar', 'rol', 'ror', 'rcl', 'rcr'):
        return 'shift_rotate'
    elif mnemonic == 'salc' or (mnemonic == 'db' and '0xd6' in decoded.lower()):
        return 'undocumented'
    elif mnemonic in ('add', 'sub', 'xor', 'or', 'and', 'cmp', 'neg', 'not',
                       'mul', 'imul', 'div', 'idiv', 'inc', 'dec'):
        return 'alu'
    else:
        return 'other'


def run_trace_against_emulator(tv):
    """Execute a trace against the current cpu8088.py, return (passed, discrepancies)."""
    # Force reimport to pick up any changes
    if 'cpu8088' in sys.modules:
        importlib.reload(sys.modules['cpu8088'])
    from cpu8088 import CPU8088

    cpu = CPU8088()
    init = tv['initial']
    for name in REG_ORDER:
        cpu.set_reg(name, init[name])
    cpu.flags = init['flags']
    cpu.ip = init['ip']

    for i, b in enumerate(tv['bytes']):
        cpu.memory[cpu.ip + i] = b

    try:
        cpu.execute_one()
    except Exception as exc:
        return False, {'error': str(exc)}

    exp = tv['expected']
    mask = tv['flags_mask']
    reg_disc = {}
    flags_disc = None

    for name in REG_ORDER:
        actual = cpu.get_reg(name)
        expected = exp[name]
        if actual != expected:
            reg_disc[name] = {'expected': expected, 'actual': actual}

    exp_flags = exp['flags']
    if (cpu.flags & mask) != (exp_flags & mask):
        flags_disc = {
            'expected_masked': exp_flags & mask,
            'actual_masked': cpu.flags & mask,
            'mask': mask,
        }

    has_errors = bool(reg_disc) or bool(flags_disc)
    disc = {}
    if reg_disc:
        disc['registers'] = reg_disc
    if flags_disc:
        disc['flags'] = flags_disc

    return not has_errors, disc


def build_conformance_report(traces):
    """Evaluate emulator against all traces and build the conformance report."""
    trace_results = []
    for tv in traces:
        decoded = decode_instruction(tv['bytes'])
        category = categorize_instruction(tv['name'], decoded)
        passed, discrepancies = run_trace_against_emulator(tv)

        entry = {
            'name': tv['name'],
            'decoded_instruction': decoded,
            'category': category,
            'status': 'pass' if passed else 'fail',
        }
        if not passed:
            entry['discrepancies'] = discrepancies
        trace_results.append(entry)

    # Group failures by category for root cause analysis
    failures_by_cat = {}
    for entry in trace_results:
        if entry['status'] == 'fail':
            cat = entry['category']
            if cat not in failures_by_cat:
                failures_by_cat[cat] = []
            failures_by_cat[cat].append(entry['name'])

    # Root cause analysis for each failure category
    root_causes = {
        'bcd_adjustment': (
            'DAA and DAS second adjustment condition checks the already-adjusted '
            'AL value instead of the saved original AL before the first adjustment. '
            'When the first adjustment modifies AL (e.g., wrapping 0xFA+6=0x00), '
            'the second condition "if al > 0x99" sees the post-adjustment value '
            'and may incorrectly skip the high-nibble adjustment. The fix is to '
            'compare old_al (saved before any adjustment) against 0x99.'
        ),
        'ascii_arithmetic': (
            'AAM and AAD hardcode the divisor/multiplier to 10 (the standard BCD '
            'base) instead of using the actual immediate byte operand following '
            'the opcode. The 8088 accepts arbitrary base values in the D4/D5 '
            'instruction encoding — for example AAM with immediate 0x07 should '
            'divide by 7, not by 10. The fix is to use the fetched _base variable '
            'instead of the literal 10.'
        ),
        'undocumented': (
            'SALC (opcode 0xD6) is an undocumented 8088 instruction that sets '
            'AL to 0xFF if the Carry Flag is set, or 0x00 if CF is clear, without '
            'modifying any flags. The emulator lacks any handler for opcode 0xD6 '
            'and raises an unhandled opcode exception. The fix is to add an '
            'elif branch for opcode 0xD6 in execute_one().'
        ),
        'shift_rotate': (
            'Shift and rotate operations mask the count with 0x1F (count & 31), '
            'which is Intel 80286 and later behavior. The real 8088 does NOT mask '
            'the shift count — it processes the full CL value, allowing shifts of '
            '32 or more that completely zero out the operand. The fix is to remove '
            'the "count = count & 0x1F" line from _shift_rotate().'
        ),
    }

    failure_analysis = {}
    for cat, affected in failures_by_cat.items():
        failure_analysis[cat] = {
            'root_cause': root_causes.get(cat, 'Unknown root cause — requires further investigation'),
            'affected_traces': affected,
        }

    passing = sum(1 for e in trace_results if e['status'] == 'pass')
    failing = len(trace_results) - passing

    report = {
        'format_version': '1.0',
        'summary': {
            'total_traces': len(trace_results),
            'passing': passing,
            'failing': failing,
        },
        'traces': trace_results,
        'failure_analysis': failure_analysis,
    }

    with open(REPORT_PATH, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Conformance report: {passing} passing, {failing} failing, "
          f"{len(failure_analysis)} failure categories")
    return report


def fix_emulator():
    """Apply patches to cpu8088.py based on conformance analysis."""
    with open(EMULATOR_PATH, 'r') as f:
        code = f.read()

    # Fix 1 & 2: DAA/DAS — second condition must use original AL
    code = code.replace(
        'if al > 0x99 or old_cf:',
        'if old_al > 0x99 or old_cf:',
    )

    # Fix 3: AAM — use immediate operand for division
    code = code.replace(
        'self.set_reg8(4, al // 10)',
        'self.set_reg8(4, al // _base)',
    )
    code = code.replace(
        'self.set_reg8(0, al % 10)',
        'self.set_reg8(0, al % _base)',
    )

    # Fix 4: AAD — use immediate operand for multiplication
    code = code.replace(
        '(ah * 10 + al)',
        '(ah * _base + al)',
    )

    # Fix 5: Remove 80286+ shift count masking
    code = code.replace(
        '        count = count & 0x1F\n',
        '',
    )

    # Fix 6: Add SALC (opcode 0xD6) handler
    salc_handler = (
        '        # SALC - Set AL from Carry (undocumented 8088 opcode)\n'
        '        elif opcode == 0xD6:\n'
        '            if self.get_flag(self.CF):\n'
        '                self.set_reg8(0, 0xFF)\n'
        '            else:\n'
        '                self.set_reg8(0, 0x00)\n\n'
    )
    code = code.replace(
        '        else:\n            raise ValueError(f"Unhandled opcode: 0x{opcode:02X}")',
        salc_handler
        + '        else:\n            raise ValueError(f"Unhandled opcode: 0x{opcode:02X}")',
    )

    with open(EMULATOR_PATH, 'w') as f:
        f.write(code)

    print("Emulator patches applied.")


def verify_fixes(traces):
    """Verify all traces pass after fixes."""
    # Clear cached module
    if 'cpu8088' in sys.modules:
        del sys.modules['cpu8088']

    all_pass = True
    for tv in traces:
        passed, disc = run_trace_against_emulator(tv)
        if not passed:
            print(f"  STILL FAILING: {tv['name']} — {disc}")
            all_pass = False

    return all_pass


def main():
    print("=== Parsing binary hardware traces ===")
    traces = parse_traces()
    print(f"Parsed {len(traces)} traces from {TRACES_PATH}")

    print("\n=== Evaluating emulator conformance ===")
    report = build_conformance_report(traces)

    print("\n=== Applying emulator fixes ===")
    fix_emulator()

    print("\n=== Verifying fixes ===")
    if verify_fixes(traces):
        print("All traces pass — emulator matches hardware.")
    else:
        print("ERROR: Some traces still failing after fix!")
        sys.exit(1)


if __name__ == '__main__':
    main()
