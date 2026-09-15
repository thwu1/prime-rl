#!/usr/bin/env python3
"""RISC-V SoC Memory Map Analyzer

Parses non-standard JSON-like SoC configuration files (with #include
preprocessing, single-quoted strings, hex literals, Python-style booleans)
and provides memory map analysis, address resolution, and configuration
validation for RISC-V System-on-Chip designs.
"""

import sys
import os
import json
import re
import ast


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
    """Parse the non-standard SoC configuration format.

    The format uses single-quoted strings, hex literals, true/false booleans,
    #include directives, and trailing commas. After preprocessing, it can be
    parsed as a Python literal using ast.literal_eval.
    """
    with open(filepath) as f:
        text = f.read()

    base_dir = os.path.dirname(os.path.abspath(filepath))
    text = preprocess_includes(text, base_dir)

    # Replace JSON-style boolean literals with Python-style
    text = re.sub(r'\btrue\b', 'True', text)
    text = re.sub(r'\bfalse\b', 'False', text)

    config = ast.literal_eval(text)
    return config


def extract_devices(config):
    """Extract all device instances with their address attributes."""
    devices = {}
    for service in config.get('Services', []):
        cls = service.get('Class', '')
        for instance in service.get('Instances', []):
            name = instance['Name']
            attrs = {}
            for attr_entry in instance.get('Attr', []):
                if len(attr_entry) >= 2:
                    attrs[attr_entry[0]] = attr_entry[1]

            devices[name] = {
                'name': name,
                'class': cls,
                'base_address': attrs.get('BaseAddress'),
                'length': attrs.get('Length'),
                'priority': attrs.get('Priority', 0),
                'read_only': attrs.get('ReadOnly', False),
            }
    return devices


def extract_buses(config):
    """Extract bus configurations with their MapList and AddrWidth."""
    buses = {}
    for service in config.get('Services', []):
        if service.get('Class') == 'BusGenericClass':
            for instance in service.get('Instances', []):
                name = instance['Name']
                attrs = {}
                for attr_entry in instance.get('Attr', []):
                    if len(attr_entry) >= 2:
                        attrs[attr_entry[0]] = attr_entry[1]
                buses[name] = {
                    'name': name,
                    'addr_width': attrs.get('AddrWidth'),
                    'map_list': attrs.get('MapList', []),
                }
    return buses


def resolve_address(devices, buses, address):
    """Resolve which device handles a given physical address.

    Priority-based resolution: highest priority wins. Among equal-priority
    devices, the one listed first in the bus MapList wins (but conflict=True).
    """
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
            'conflict': False,
            'error': 'address_out_of_range',
        }

    # Collect all matching devices in MapList order
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
            'conflict': False,
        }

    # Find highest priority among matches
    max_priority = max(m['priority'] for m in matches)
    top_matches = [m for m in matches if m['priority'] == max_priority]

    # First device in MapList order among highest-priority matches wins
    winner = top_matches[0]
    conflict = len(top_matches) > 1

    return {
        'address': hex(address),
        'device': winner['name'],
        'offset': hex(address - winner['base_address']),
        'read_only': winner['read_only'],
        'priority': winner['priority'],
        'conflict': conflict,
    }


def validate_config(devices, buses):
    """Validate the SoC configuration for common hardware issues."""
    errors = []
    bus = list(buses.values())[0]

    # 1. Undefined devices referenced in MapList
    for dev_name in bus['map_list']:
        if dev_name not in devices:
            errors.append({
                'type': 'undefined_device',
                'device': dev_name,
                'bus': bus['name'],
            })

    # 2. Address overlaps at same priority among mapped devices
    mapped = []
    for dev_name in bus['map_list']:
        if dev_name in devices:
            dev = devices[dev_name]
            if dev['base_address'] is not None and dev['length'] is not None:
                mapped.append(dev)

    for i in range(len(mapped)):
        for j in range(i + 1, len(mapped)):
            d1, d2 = mapped[i], mapped[j]
            s1, e1 = d1['base_address'], d1['base_address'] + d1['length']
            s2, e2 = d2['base_address'], d2['base_address'] + d2['length']
            overlap_start = max(s1, s2)
            overlap_end = min(e1, e2)
            if overlap_start < overlap_end and d1['priority'] == d2['priority']:
                errors.append({
                    'type': 'address_overlap',
                    'devices': [d1['name'], d2['name']],
                    'range': [hex(overlap_start), hex(overlap_end)],
                })

    # 3. Orphan devices (defined with an address but not in any bus MapList)
    all_mapped = set()
    for b in buses.values():
        all_mapped.update(b['map_list'])

    non_addressable_classes = {
        'CpuRiver_FunctionalClass', 'CpuRiscV_RTLClass',
        'BusGenericClass', 'ICacheFunctionalClass',
        'RiscvSourceServiceClass', 'GuiPluginClass',
    }
    for dev_name, dev in devices.items():
        if (dev_name not in all_mapped
                and dev['base_address'] is not None
                and dev['class'] not in non_addressable_classes):
            errors.append({
                'type': 'orphan_device',
                'device': dev_name,
            })

    # 4. Device addresses exceeding bus AddrWidth
    addr_width = bus['addr_width']
    max_addr = 1 << addr_width
    for dev_name in bus['map_list']:
        if dev_name in devices:
            dev = devices[dev_name]
            if dev['base_address'] is not None and dev['base_address'] >= max_addr:
                errors.append({
                    'type': 'address_exceeds_width',
                    'device': dev_name,
                    'bus': bus['name'],
                    'addr_width': addr_width,
                })

    return {'errors': errors}


def generate_map(devices, buses):
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
            'priority': dev['priority'],
            'read_only': dev['read_only'],
            'class': dev['class'],
            'bus': bus['name'],
        })

    entries.sort(key=lambda e: int(e['base_address'], 16))
    return entries


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: mmap_analyzer.py <command> <config_file> [args...]\n"
            "Commands: resolve, validate, map",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    config_file = sys.argv[2]

    config = parse_config(config_file)
    devices = extract_devices(config)
    buses = extract_buses(config)

    if command == 'resolve':
        if len(sys.argv) < 4:
            print(
                "Usage: mmap_analyzer.py resolve <config_file> <hex_address>",
                file=sys.stderr,
            )
            sys.exit(1)
        address = int(sys.argv[3], 16)
        result = resolve_address(devices, buses, address)
        print(json.dumps(result, indent=2))

    elif command == 'validate':
        result = validate_config(devices, buses)
        print(json.dumps(result, indent=2))

    elif command == 'map':
        result = generate_map(devices, buses)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
