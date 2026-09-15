#!/usr/bin/env python3
"""RISC-V SoC Configuration Cross-Reference Analyzer

Parses the riscv_vhdl debugger's non-standard JSON-like configuration files
and VHDL hardware constant declarations, providing memory map analysis,
address resolution, and cross-validation between simulation config and RTL.
"""

import sys
import os
import json
import re
import ast


# ---------------------------------------------------------------------------
# Config parser (non-standard JSON-like format with #include)
# ---------------------------------------------------------------------------

def preprocess_includes(text, base_dir, visited=None):
    """Recursively process #include directives."""
    if visited is None:
        visited = set()
    lines = text.split('\n')
    result = []
    for line in lines:
        m = re.match(r'\s*#include\s+"([^"]+)"', line)
        if m:
            filename = m.group(1)
            include_path = os.path.normpath(os.path.join(base_dir, filename))
            if include_path in visited:
                raise ValueError(f"Circular include detected: {include_path}")
            visited.add(include_path)
            with open(include_path) as f:
                included_text = f.read()
            included_text = preprocess_includes(
                included_text, os.path.dirname(include_path), visited
            )
            result.append(included_text)
        else:
            result.append(line)
    return '\n'.join(result)


def parse_config(filepath):
    """Parse the non-standard SoC configuration format."""
    with open(filepath) as f:
        text = f.read()

    base_dir = os.path.dirname(os.path.abspath(filepath))
    text = preprocess_includes(text, base_dir)

    # Replace boolean literals
    text = re.sub(r'\btrue\b', 'True', text)
    text = re.sub(r'\bfalse\b', 'False', text)

    config = ast.literal_eval(text)
    return config


# ---------------------------------------------------------------------------
# VHDL parser (extract constant declarations from a VHDL package)
# ---------------------------------------------------------------------------

def parse_vhdl_constants(filepath):
    """Extract constant definitions from a VHDL package file."""
    with open(filepath) as f:
        text = f.read()

    constants = {}
    # Match: constant NAME : TYPE := VALUE;
    pattern = re.compile(
        r'constant\s+(\w+)\s*:\s*[^:]+?:=\s*(.+?)\s*;',
        re.IGNORECASE
    )

    for m in pattern.finditer(text):
        name = m.group(1)
        raw_value = m.group(2).strip()

        # Parse the value
        value = parse_vhdl_value(raw_value, constants)
        if value is not None:
            constants[name] = value

    return constants


def parse_vhdl_value(raw, known_constants=None):
    """Parse a VHDL constant value expression."""
    raw = raw.strip()

    # X"hex_string" → integer
    hex_match = re.match(r'^[Xx]"([0-9A-Fa-f]+)"$', raw)
    if hex_match:
        return int(hex_match.group(1), 16)

    # "binary_string" → keep as string (for std_logic_vector literals)
    bin_match = re.match(r'^"([01]+)"$', raw)
    if bin_match:
        return int(bin_match.group(1), 2)

    # Boolean
    if raw.lower() == 'true':
        return True
    if raw.lower() == 'false':
        return False

    # Integer literal
    try:
        return int(raw)
    except ValueError:
        pass

    # Expression: 2**NAME or 2**N
    power_match = re.match(r'^(\d+)\s*\*\*\s*(\w+)$', raw)
    if power_match:
        base = int(power_match.group(1))
        exp_name = power_match.group(2)
        try:
            exp_val = int(exp_name)
        except ValueError:
            if known_constants and exp_name in known_constants:
                exp_val = known_constants[exp_name]
            else:
                return None
        return base ** exp_val

    # Expression: N*CONST or similar multiplications
    mult_match = re.match(r'^(\d+)\s*\*\s*(\w+)$', raw)
    if mult_match:
        left = int(mult_match.group(1))
        right_name = mult_match.group(2)
        if known_constants and right_name in known_constants:
            return left * known_constants[right_name]
        return None

    # Parenthesized: (others => 'X')
    if raw.startswith('('):
        return None

    return None


# ---------------------------------------------------------------------------
# Device and bus extraction
# ---------------------------------------------------------------------------

def extract_devices(config):
    """Extract all device instances with their address attributes."""
    devices = {}
    for service in config.get('Services', []):
        cls = service.get('Class', '')
        for instance in service.get('Instances', []):
            name = instance['Name']
            attrs = {}
            for attr_entry in instance.get('Attr', []):
                if isinstance(attr_entry, list) and len(attr_entry) >= 2:
                    attrs[attr_entry[0]] = attr_entry[1]

            devices[name] = {
                'name': name,
                'class': cls,
                'attrs': attrs,
                'base_address': attrs.get('BaseAddress'),
                'length': attrs.get('Length'),
                'priority': attrs.get('Priority', 0),
                'read_only': attrs.get('ReadOnly', False),
            }
    return devices


def extract_buses(config):
    """Extract bus configurations (BusGenericClass instances)."""
    buses = {}
    for service in config.get('Services', []):
        if service.get('Class') == 'BusGenericClass':
            for instance in service.get('Instances', []):
                name = instance['Name']
                attrs = {}
                for attr_entry in instance.get('Attr', []):
                    if isinstance(attr_entry, list) and len(attr_entry) >= 2:
                        attrs[attr_entry[0]] = attr_entry[1]

                # Filter MapList to only string entries (exclude sub-module refs like ['core0','dmi'])
                raw_map = attrs.get('MapList', [])
                map_list = [x for x in raw_map if isinstance(x, str)]

                buses[name] = {
                    'name': name,
                    'addr_width': attrs.get('AddrWidth'),
                    'map_list': map_list,
                }
    return buses


# ---------------------------------------------------------------------------
# memmap command
# ---------------------------------------------------------------------------

def generate_memmap(devices, buses):
    """Generate the memory map sorted by base address."""
    bus = list(buses.values())[0]
    entries = []

    for dev_name in bus['map_list']:
        if dev_name not in devices:
            continue
        dev = devices[dev_name]
        if dev['base_address'] is None or dev['length'] is None:
            continue
        entries.append({
            'name': dev['name'],
            'base_address': hex(dev['base_address']),
            'end_address': hex(dev['base_address'] + dev['length']),
            'length': hex(dev['length']),
            'class': dev['class'],
            'bus': bus['name'],
        })

    entries.sort(key=lambda e: int(e['base_address'], 16))
    return entries


# ---------------------------------------------------------------------------
# resolve command
# ---------------------------------------------------------------------------

def resolve_address(devices, buses, address):
    """Resolve which device handles a given physical address."""
    bus = list(buses.values())[0]
    addr_width = bus['addr_width']
    max_addr = 1 << addr_width

    if address >= max_addr:
        return {
            'address': hex(address),
            'device': None,
            'offset': None,
            'read_only': None,
            'priority': None,
            'error': 'address_out_of_range',
        }

    # Find matching devices in MapList order
    matches = []
    for dev_name in bus['map_list']:
        if dev_name not in devices:
            continue
        dev = devices[dev_name]
        base = dev['base_address']
        length = dev['length']
        if base is None or length is None:
            continue
        if base <= address < base + length:
            matches.append(dev)

    if not matches:
        return {
            'address': hex(address),
            'device': None,
            'offset': None,
            'read_only': None,
            'priority': None,
        }

    # Highest priority wins
    max_priority = max(m['priority'] for m in matches)
    top_matches = [m for m in matches if m['priority'] == max_priority]
    winner = top_matches[0]

    return {
        'address': hex(address),
        'device': winner['name'],
        'offset': hex(address - winner['base_address']),
        'read_only': winner['read_only'],
        'priority': winner['priority'],
    }


# ---------------------------------------------------------------------------
# crosscheck command
# ---------------------------------------------------------------------------

def crosscheck(devices, config, vhdl_constants):
    """Cross-validate JSON simulation config against VHDL hardware constants."""
    checks = []

    # Get core0 and dmi0 attributes
    core0 = devices.get('core0', {})
    core0_attrs = core0.get('attrs', {})
    dmi0 = devices.get('dmi0', {})
    dmi0_attrs = dmi0.get('attrs', {})

    # 1. VendorID
    json_vid = core0_attrs.get('VendorID')
    vhdl_vid = vhdl_constants.get('CFG_VENDOR_ID')
    checks.append({
        'parameter': 'vendor_id',
        'json_value': hex(json_vid) if json_vid is not None else None,
        'vhdl_value': hex(vhdl_vid) if vhdl_vid is not None else None,
        'status': 'match' if json_vid == vhdl_vid else 'mismatch',
    })

    # 2. ImplementationID
    json_iid = core0_attrs.get('ImplementationID')
    vhdl_iid = vhdl_constants.get('CFG_IMPLEMENTATION_ID')
    checks.append({
        'parameter': 'implementation_id',
        'json_value': hex(json_iid) if json_iid is not None else None,
        'vhdl_value': hex(vhdl_iid) if vhdl_iid is not None else None,
        'status': 'match' if json_iid == vhdl_iid else 'mismatch',
    })

    # 3. FPU enabled
    list_ext = core0_attrs.get('ListExtISA', [])
    json_fpu = 'D' in list_ext if isinstance(list_ext, list) else False
    vhdl_fpu = vhdl_constants.get('CFG_HW_FPU_ENABLE', False)
    checks.append({
        'parameter': 'fpu_enabled',
        'json_value': json_fpu,
        'vhdl_value': vhdl_fpu,
        'status': 'match' if json_fpu == vhdl_fpu else 'mismatch',
    })

    # 4. ProgbufTotal
    json_pb = dmi0_attrs.get('ProgbufTotal')
    vhdl_pb = vhdl_constants.get('CFG_PROGBUF_REG_TOTAL')
    checks.append({
        'parameter': 'progbuf_total',
        'json_value': json_pb,
        'vhdl_value': vhdl_pb,
        'status': 'match' if json_pb == vhdl_pb else 'mismatch',
    })

    # 5. DataregTotal
    json_dr = dmi0_attrs.get('DataregTotal')
    vhdl_dr = vhdl_constants.get('CFG_DATA_REG_TOTAL')
    checks.append({
        'parameter': 'data_reg_total',
        'json_value': json_dr,
        'vhdl_value': vhdl_dr,
        'status': 'match' if json_dr == vhdl_dr else 'mismatch',
    })

    # 6. StackTraceSize
    json_st = core0_attrs.get('StackTraceSize')
    vhdl_log2 = vhdl_constants.get('CFG_LOG2_STACK_TRACE_ADDR')
    vhdl_st = (2 ** vhdl_log2) if vhdl_log2 is not None else None
    checks.append({
        'parameter': 'stack_trace_size',
        'json_value': json_st,
        'vhdl_value': vhdl_st,
        'status': 'match' if json_st == vhdl_st else 'mismatch',
    })

    # 7. ResetVector
    json_rv = core0_attrs.get('ResetVector')
    vhdl_rv = vhdl_constants.get('CFG_NMI_RESET_VECTOR')
    checks.append({
        'parameter': 'reset_vector',
        'json_value': hex(json_rv) if json_rv is not None else None,
        'vhdl_value': hex(vhdl_rv) if vhdl_rv is not None else None,
        'status': 'match' if json_rv == vhdl_rv else 'mismatch',
    })

    matches = sum(1 for c in checks if c['status'] == 'match')
    mismatches = sum(1 for c in checks if c['status'] == 'mismatch')

    return {
        'checks': checks,
        'summary': {
            'total': len(checks),
            'matches': matches,
            'mismatches': mismatches,
        },
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print(
            "Usage: soc_analyzer.py <command> <config_file> [args...]\n"
            "Commands: memmap, resolve, crosscheck",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    config_file = sys.argv[2]

    config = parse_config(config_file)
    devices = extract_devices(config)
    buses = extract_buses(config)

    if command == 'memmap':
        result = generate_memmap(devices, buses)
        print(json.dumps(result, indent=2))

    elif command == 'resolve':
        if len(sys.argv) < 4:
            print("Usage: soc_analyzer.py resolve <config_file> <hex_address>",
                  file=sys.stderr)
            sys.exit(1)
        address = int(sys.argv[3], 16)
        result = resolve_address(devices, buses, address)
        print(json.dumps(result, indent=2))

    elif command == 'crosscheck':
        if len(sys.argv) < 4:
            print("Usage: soc_analyzer.py crosscheck <config_file> <vhdl_file>",
                  file=sys.stderr)
            sys.exit(1)
        vhdl_file = sys.argv[3]
        vhdl_constants = parse_vhdl_constants(vhdl_file)
        result = crosscheck(devices, config, vhdl_constants)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
