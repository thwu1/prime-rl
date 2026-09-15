#!/usr/bin/env python3

"""Verify cross-format float conformance audit output and C++ float tool."""

import struct
import math
import os
import json
import subprocess
import pytest

# ========================
# File paths
# ========================
BINARY_FILE = "/app/data/vectors/base_values.bin"
TEXT_FILE = "/app/data/samples/lab_readings.txt"
CSV_FILE = "/app/data/imports/eu_sensor_data.csv"
HEX_FILE = "/app/data/reference/ieee754_hex.txt"
JSON_FILE = "/app/data/archive/constants.json"
OUTPUT_FILE = "/app/output/audit.csv"
FLOAT_TOOL = "/app/build/float_tool"


# ========================
# Helpers
# ========================

def float_to_bits(d):
    return struct.unpack('<Q', struct.pack('<d', d))[0]


def bits_to_float(bits):
    return struct.unpack('<d', struct.pack('<Q', bits))[0]


def classify(bits):
    exp = (bits >> 52) & 0x7FF
    mant = bits & 0x000FFFFFFFFFFFFF
    if exp == 0x7FF:
        return "nan" if mant else "infinity"
    if exp == 0 and mant == 0:
        return "zero"
    if exp == 0:
        return "subnormal"
    return "normal"


# ========================
# Reference shortest-string
# ========================

def find_min_sig(d_abs, abs_bits):
    for n in range(1, 18):
        s = f"{d_abs:.{n-1}e}"
        if float_to_bits(float(s)) == abs_bits:
            return n
    return 17


def gen_fixed(d_abs, sig):
    s = f"{d_abs:.{sig-1}e}"
    parts = s.split('e')
    digits = parts[0].replace('.', '').replace('-', '')
    exp = int(parts[1])
    if exp >= sig - 1:
        result = digits + '0' * (exp - sig + 1)
    elif exp >= 0:
        result = digits[:exp+1] + '.' + digits[exp+1:]
    else:
        result = '0.' + '0' * (-exp-1) + digits
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return result


def gen_sci(d_abs, sig):
    s = f"{d_abs:.{sig-1}e}"
    parts = s.split('e')
    mantissa = parts[0]
    exp = int(parts[1])
    if '.' in mantissa:
        mantissa = mantissa.rstrip('0').rstrip('.')
    return f"{mantissa}e{exp}"


def shortest_string(bits):
    exp_field = (bits >> 52) & 0x7FF
    mant_field = bits & 0x000FFFFFFFFFFFFF
    sign = bits >> 63
    if exp_field == 0x7FF:
        if mant_field:
            return "nan"
        return "-inf" if sign else "inf"
    d = bits_to_float(bits)
    if d == 0.0:
        return "-0" if sign else "0"
    prefix = "-" if sign else ""
    d_abs = abs(d)
    abs_bits = bits & 0x7FFFFFFFFFFFFFFF
    n = find_min_sig(d_abs, abs_bits)
    fixed = prefix + gen_fixed(d_abs, n)
    sci = prefix + gen_sci(d_abs, n)
    return fixed if len(fixed) <= len(sci) else sci


# ========================
# Data source parsers
# ========================

def parse_binary(path):
    result = []
    with open(path, 'rb') as f:
        count = struct.unpack('<I', f.read(4))[0]
        for _ in range(count):
            bits = struct.unpack('<Q', f.read(8))[0]
            result.append(bits)
    return result


def parse_text(path):
    result = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            result.append(float_to_bits(float(line)))
    return result


def parse_csv_european(path):
    result = []
    with open(path, 'r') as f:
        f.readline()  # skip header
        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = line.split(';')
            val_str = fields[2].strip()
            low = val_str.lower()
            if low == 'nan':
                result.append(float_to_bits(float('nan')))
            elif low in ('inf', 'infinity'):
                result.append(float_to_bits(float('inf')))
            elif low in ('-inf', '-infinity'):
                result.append(float_to_bits(float('-inf')))
            else:
                val_str = val_str.replace(',', '.')
                result.append(float_to_bits(float(val_str)))
    return result


def parse_hex(path):
    result = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            bits = int(line, 16)
            result.append(bits)
    return result


def parse_json_strings(path):
    with open(path, 'r') as f:
        data = json.load(f)
    result = []
    for s in data["values"]:
        low = s.strip().lower()
        if low == 'nan':
            result.append(float_to_bits(float('nan')))
        elif low in ('infinity', 'inf'):
            result.append(float_to_bits(float('inf')))
        elif low in ('-infinity', '-inf'):
            result.append(float_to_bits(float('-inf')))
        elif s.strip() == '-0':
            result.append(1 << 63)
        elif s.strip() == '0':
            result.append(0)
        else:
            result.append(float_to_bits(float(s)))
    return result


def load_all_sources():
    """Parse all 5 data sources. Returns {bits: set_of_source_paths}."""
    parsers = {
        BINARY_FILE: parse_binary,
        TEXT_FILE: parse_text,
        CSV_FILE: parse_csv_european,
        HEX_FILE: parse_hex,
        JSON_FILE: parse_json_strings,
    }
    all_values = {}
    for path, parser in parsers.items():
        for bits in parser(path):
            if bits not in all_values:
                all_values[bits] = set()
            all_values[bits].add(path)
    return all_values


def compute_expected():
    """Compute full expected audit.csv rows."""
    all_values = load_all_sources()
    rows = []
    for bits in sorted(all_values.keys()):
        rows.append((
            f"{bits:016x}",
            shortest_string(bits),
            len(all_values[bits]),
            classify(bits),
        ))
    return rows


# ========================
# Tests: C++ float tool
# ========================

class TestFloatTool:

    def test_exists_and_executable(self):
        assert os.path.exists(FLOAT_TOOL), \
            f"C++ float tool not found at {FLOAT_TOOL}"
        assert os.access(FLOAT_TOOL, os.X_OK), \
            f"{FLOAT_TOOL} is not executable"

    def test_parses_decimal_strings(self):
        if not os.path.exists(FLOAT_TOOL):
            pytest.skip("Float tool not built")

        test_cases = [
            ("3.14", float_to_bits(3.14)),
            ("1e-20", float_to_bits(1e-20)),
            ("0.1", float_to_bits(0.1)),
            ("100", float_to_bits(100.0)),
            ("0.00011", float_to_bits(0.00011)),
            ("-3.14", float_to_bits(-3.14)),
            ("5e-324", float_to_bits(5e-324)),
            ("1.7976931348623157e308", float_to_bits(1.7976931348623157e308)),
        ]

        input_str = "\n".join(s for s, _ in test_cases) + "\n"
        result = subprocess.run(
            [FLOAT_TOOL], input=input_str,
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, \
            f"Exit code {result.returncode}: {result.stderr}"

        output_lines = [l.strip() for l in result.stdout.strip().split('\n')
                        if l.strip()]
        assert len(output_lines) == len(test_cases), \
            f"Expected {len(test_cases)} output lines, got {len(output_lines)}"

        for (inp, expected_bits), out_hex in zip(test_cases, output_lines):
            expected_hex = f"{expected_bits:016x}"
            assert out_hex == expected_hex, \
                f"Input '{inp}': expected {expected_hex}, got {out_hex}"


# ========================
# Tests: audit.csv output
# ========================

class TestAuditOutput:

    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.exists(OUTPUT_FILE), \
            f"Output file {OUTPUT_FILE} missing"
        self.expected = compute_expected()
        with open(OUTPUT_FILE, 'r') as f:
            self.lines = [l.strip() for l in f if l.strip()]

    def _parse_row(self, line):
        parts = line.split(',')
        return parts[0], parts[1], int(parts[2]), parts[3]

    def test_row_count(self):
        assert len(self.lines) == len(self.expected), \
            f"Expected {len(self.expected)} rows, got {len(self.lines)}. " \
            f"Did you discover all 5 data sources under /app/data/?"

    def test_round_trip(self):
        failures = []
        for i, line in enumerate(self.lines):
            parts = line.split(',')
            if len(parts) < 4:
                failures.append(f"Row {i}: malformed '{line}'")
                continue
            hex_bits, short_str = parts[0], parts[1]
            try:
                bits = int(hex_bits, 16)
            except ValueError:
                failures.append(f"Row {i}: bad hex '{hex_bits}'")
                continue
            if classify(bits) == "nan":
                if short_str != "nan":
                    failures.append(f"Row {i}: NaN should be 'nan', got '{short_str}'")
                continue
            try:
                parsed = float(short_str)
            except ValueError:
                failures.append(f"Row {i}: cannot parse '{short_str}'")
                continue
            pbits = float_to_bits(parsed)
            if pbits != bits:
                failures.append(
                    f"Row {i}: {hex_bits} -> '{short_str}' -> {pbits:016x}"
                )
        assert not failures, "Round-trip failures:\n" + "\n".join(failures[:25])

    def test_minimality(self):
        failures = []
        for i, line in enumerate(self.lines):
            parts = line.split(',')
            if len(parts) < 4:
                continue
            bits = int(parts[0], 16)
            cat = classify(bits)
            if cat in ("nan", "infinity", "zero"):
                continue
            d_abs = abs(bits_to_float(bits))
            abs_bits = bits & 0x7FFFFFFFFFFFFFFF
            min_sig = find_min_sig(d_abs, abs_bits)
            if min_sig > 1:
                shorter = f"{d_abs:.{min_sig-2}e}"
                if float_to_bits(float(shorter)) == abs_bits:
                    failures.append(
                        f"Row {i}: {min_sig-1} sig digits suffice for {parts[0]}"
                    )
        assert not failures, \
            "Minimality failures:\n" + "\n".join(failures[:25])

    def test_notation_optimality(self):
        failures = []
        for i, (exp_hex, exp_short, _, exp_cat) in enumerate(self.expected):
            if i >= len(self.lines):
                break
            if exp_cat in ("nan", "infinity", "zero"):
                continue
            parts = self.lines[i].split(',')
            if len(parts) < 4:
                continue
            agent_short = parts[1]
            if len(agent_short) > len(exp_short):
                failures.append(
                    f"Row {i}: '{agent_short}' ({len(agent_short)} ch) "
                    f"vs optimal '{exp_short}' ({len(exp_short)} ch)"
                )
        assert not failures, \
            "Notation optimality failures:\n" + "\n".join(failures[:25])

    def test_categories(self):
        failures = []
        for i, line in enumerate(self.lines):
            parts = line.split(',')
            if len(parts) < 4:
                failures.append(f"Row {i}: malformed")
                continue
            bits = int(parts[0], 16)
            reported = parts[3]
            expected = classify(bits)
            if reported != expected:
                failures.append(
                    f"Row {i}: {parts[0]} cat '{reported}' != '{expected}'"
                )
        assert not failures, \
            "Category failures:\n" + "\n".join(failures[:25])

    def test_source_counts(self):
        all_values = load_all_sources()
        failures = []
        for i, line in enumerate(self.lines):
            parts = line.split(',')
            if len(parts) < 4:
                continue
            bits = int(parts[0], 16)
            reported = int(parts[2])
            expected = len(all_values.get(bits, set()))
            if reported != expected:
                failures.append(
                    f"Row {i}: {parts[0]} source_count {reported} != {expected}"
                )
        assert not failures, \
            "Source count failures:\n" + "\n".join(failures[:25])

    def test_sort_order(self):
        prev = -1
        for i, line in enumerate(self.lines):
            bits = int(line.split(',')[0], 16)
            assert bits > prev, \
                f"Row {i}: sort violation {line.split(',')[0]} <= prev"
            prev = bits

    def test_hex_format(self):
        failures = []
        for i, line in enumerate(self.lines):
            h = line.split(',')[0]
            if len(h) != 16:
                failures.append(f"Row {i}: hex '{h}' not 16 chars")
            elif h != h.lower():
                failures.append(f"Row {i}: hex '{h}' not lowercase")
            elif not all(c in '0123456789abcdef' for c in h):
                failures.append(f"Row {i}: hex '{h}' invalid chars")
        assert not failures, \
            "Hex format failures:\n" + "\n".join(failures[:25])

    def test_format_rules(self):
        failures = []
        for i, line in enumerate(self.lines):
            s = line.split(',')[1]
            if s in ("nan", "inf", "-inf", "0", "-0"):
                continue
            core = s.lstrip('-')
            if 'e' in core:
                base, exp_part = core.split('e', 1)
            else:
                base = core
                exp_part = None
            if '.' in base:
                if base.endswith('0'):
                    failures.append(f"Row {i}: trailing zero '{s}'")
                if base.endswith('.'):
                    failures.append(f"Row {i}: trailing point '{s}'")
            if exp_part is not None:
                if exp_part.startswith('+'):
                    failures.append(f"Row {i}: '+' in exponent '{s}'")
                raw = exp_part.lstrip('-')
                if len(raw) > 1 and raw.startswith('0'):
                    failures.append(f"Row {i}: leading zero in exp '{s}'")
            if exp_part is None and core.startswith('.'):
                failures.append(f"Row {i}: missing leading zero '{s}'")
        assert not failures, \
            "Format violations:\n" + "\n".join(failures[:25])
