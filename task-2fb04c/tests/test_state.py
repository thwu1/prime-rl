"""
Pytest tests for 8088 CPU emulator hardware conformance.

Verifies:
1. The fixed emulator passes all binary hardware traces
2. The conformance report is correctly structured and accurate
3. Decoded instructions in the report match ndisasm output

"""

import json
import os
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, '/app')

TRACES_PATH = '/app/traces.bin'
REPORT_PATH = '/app/conformance_report.json'
REG_ORDER = ['ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di']


def parse_traces():
    """Parse the binary trace file from /app/traces.bin."""
    with open(TRACES_PATH, 'rb') as f:
        data = f.read()

    magic = data[:4]
    assert magic == b'8T88', f"Bad magic: {magic!r}"
    version, count = struct.unpack('<HH', data[4:8])

    payload = len(data) - 8
    record_size = payload // count
    assert record_size * count == payload, "Records don't evenly divide payload"

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

        # Undocumented flags comparison mask at bytes 79-80
        flags_mask = struct.unpack('<H', rec[79:81])[0] if record_size >= 81 else 0x08D5

        traces.append({
            'name': name,
            'bytes': insn_bytes,
            'initial': dict(zip(REG_ORDER, init_regs), flags=init_flags, ip=init_ip),
            'expected': dict(zip(REG_ORDER, exp_regs), flags=exp_flags),
            'flags_mask': flags_mask,
        })
        offset += record_size

    return traces


TRACES = parse_traces()

# Lazy CPU class loader
_cpu_class = None


def _get_cpu_class():
    global _cpu_class
    if _cpu_class is None:
        from cpu8088 import CPU8088
        _cpu_class = CPU8088
    return _cpu_class


def _run_trace(tv):
    """Execute a single trace against the emulator, return list of error strings."""
    CPU8088 = _get_cpu_class()
    cpu = CPU8088()

    init = tv['initial']
    for name in REG_ORDER:
        if name in init:
            cpu.set_reg(name, init[name])
    cpu.flags = init.get('flags', 2)
    cpu.ip = init.get('ip', 0x1000)

    start_ip = cpu.ip
    for i, b in enumerate(tv['bytes']):
        cpu.memory[start_ip + i] = b

    try:
        cpu.execute_one()
    except Exception as exc:
        return [f"Exception during execution: {exc}"]

    expected = tv['expected']
    mask = tv.get('flags_mask', 0x08D5)
    errors = []

    for name in REG_ORDER:
        if name in expected:
            actual = cpu.get_reg(name)
            exp = expected[name]
            if actual != exp:
                errors.append(
                    f"{name}: expected 0x{exp:04X}, got 0x{actual:04X}"
                )

    exp_flags = expected.get('flags', 2)
    if (cpu.flags & mask) != (exp_flags & mask):
        errors.append(
            f"flags: expected 0x{exp_flags & mask:04X}, "
            f"got 0x{cpu.flags & mask:04X} "
            f"(raw=0x{cpu.flags:04X}, mask=0x{mask:04X})"
        )

    return errors


# === Hardware trace conformance tests ===

@pytest.mark.parametrize(
    "tv",
    TRACES,
    ids=[v['name'] for v in TRACES],
)
def test_trace_passes(tv):
    """Each hardware-captured trace must pass after emulator fixes."""
    errors = _run_trace(tv)
    assert not errors, (
        f"Trace '{tv['name']}' failed:\n" + "\n".join(errors)
    )


def test_all_traces_present():
    """Verify the binary trace file has the expected number of traces."""
    assert len(TRACES) >= 25, (
        f"Expected at least 25 traces, found {len(TRACES)}"
    )


# === Conformance report structure tests ===

class TestConformanceReport:
    """Verify the conformance analysis report is complete and accurate."""

    @pytest.fixture
    def report(self):
        assert os.path.exists(REPORT_PATH), (
            f"Conformance report not found at {REPORT_PATH}"
        )
        with open(REPORT_PATH) as f:
            return json.load(f)

    def test_has_summary(self, report):
        """Report must have a summary with counts."""
        assert 'summary' in report, "Report missing 'summary' field"
        s = report['summary']
        assert 'total_traces' in s
        assert 'passing' in s
        assert 'failing' in s
        assert s['total_traces'] == len(TRACES)
        assert s['passing'] + s['failing'] == s['total_traces']

    def test_has_all_trace_entries(self, report):
        """Report must have an entry for every trace."""
        assert 'traces' in report, "Report missing 'traces' field"
        assert len(report['traces']) == len(TRACES), (
            f"Expected {len(TRACES)} trace entries, found {len(report['traces'])}"
        )

    def test_trace_entry_fields(self, report):
        """Each trace entry must have required fields."""
        for entry in report['traces']:
            assert 'name' in entry, f"Trace entry missing 'name'"
            assert 'decoded_instruction' in entry, (
                f"Trace '{entry.get('name', '?')}' missing 'decoded_instruction'"
            )
            assert 'category' in entry, (
                f"Trace '{entry.get('name', '?')}' missing 'category'"
            )
            assert 'status' in entry, (
                f"Trace '{entry.get('name', '?')}' missing 'status'"
            )
            assert entry['status'] in ('pass', 'fail'), (
                f"Trace '{entry['name']}' has invalid status: {entry['status']}"
            )
            assert len(entry['decoded_instruction']) > 0, (
                f"Trace '{entry['name']}' has empty decoded_instruction"
            )

    def test_decoded_instructions_match_ndisasm(self, report):
        """Cross-check decoded instructions against ndisasm output."""
        matched = 0
        checked = 0
        for entry in report['traces']:
            # Find corresponding trace
            tv = next((t for t in TRACES if t['name'] == entry['name']), None)
            if tv is None:
                continue
            insn_bytes = bytes(tv['bytes'])
            result = subprocess.run(
                ['ndisasm', '-b', '16', '-'],
                input=insn_bytes,
                capture_output=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue
            ndisasm_line = result.stdout.decode('ascii', errors='replace').strip().split('\n')[0]
            parts = ndisasm_line.split(None, 2)
            if len(parts) < 3:
                continue
            checked += 1
            ndisasm_mnemonic = parts[2].split()[0].lower()
            report_mnemonic = entry['decoded_instruction'].split()[0].lower()
            if ndisasm_mnemonic == report_mnemonic:
                matched += 1

        assert checked > 0, "Could not cross-check any instructions with ndisasm"
        match_rate = matched / checked
        assert match_rate >= 0.7, (
            f"Only {matched}/{checked} decoded instruction mnemonics match ndisasm "
            f"({match_rate:.0%}). Expected >= 70%"
        )

    def test_has_failure_analysis(self, report):
        """Report must identify at least 4 distinct failure categories."""
        assert 'failure_analysis' in report, (
            "Report missing 'failure_analysis' field"
        )
        analysis = report['failure_analysis']
        assert len(analysis) >= 4, (
            f"Expected at least 4 failure categories, found {len(analysis)}: "
            f"{list(analysis.keys())}"
        )

    def test_failure_analysis_structure(self, report):
        """Each failure category must have root_cause and affected_traces."""
        for cat_name, cat_info in report['failure_analysis'].items():
            assert 'root_cause' in cat_info, (
                f"Category '{cat_name}' missing 'root_cause'"
            )
            assert 'affected_traces' in cat_info, (
                f"Category '{cat_name}' missing 'affected_traces'"
            )
            assert len(cat_info['affected_traces']) > 0, (
                f"Category '{cat_name}' has empty affected_traces"
            )
            words = cat_info['root_cause'].split()
            assert len(words) >= 10, (
                f"Category '{cat_name}' root_cause too brief ({len(words)} words): "
                f"'{cat_info['root_cause']}'"
            )

    def test_total_affected_traces(self, report):
        """Failure analysis must cover a significant number of traces."""
        total = sum(
            len(c['affected_traces'])
            for c in report['failure_analysis'].values()
        )
        assert total >= 10, (
            f"Failure analysis covers only {total} affected traces, expected >= 10"
        )

    def test_report_identifies_failures(self, report):
        """Report should show that the original emulator had failures."""
        assert report['summary']['failing'] > 0, (
            "Report should document pre-fix failures (failing count should be > 0)"
        )

    def test_trace_names_match(self, report):
        """All trace names in report must correspond to actual traces."""
        trace_names = {t['name'] for t in TRACES}
        for entry in report['traces']:
            assert entry['name'] in trace_names, (
                f"Report trace '{entry['name']}' not found in binary traces"
            )
