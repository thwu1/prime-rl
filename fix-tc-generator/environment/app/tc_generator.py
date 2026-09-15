#!/usr/bin/env python3
"""
TC Configuration Generator for Datacenter HTB Traffic Shaping.

Reads bandwidth_spec.yaml and generates:
  - tc_commands.sh: shell script with tc commands for the HTB hierarchy
  - tc_report.json: structured JSON report of the full configuration
"""
import yaml
import json
import os


def load_spec(path):
    with open(path) as f:
        return yaml.safe_load(f)


def dscp_to_tos(dscp_value):
    """Convert DSCP value to the TOS byte value used in tc u32 filters."""
    return dscp_value


def rate_to_mbit(rate_str):
    """Convert rate string to megabits for validation."""
    rate_str = rate_str.lower().strip()
    if rate_str.endswith('gbit'):
        return float(rate_str.replace('gbit', '')) * 1000
    elif rate_str.endswith('mbit'):
        return float(rate_str.replace('mbit', ''))
    elif rate_str.endswith('kbit'):
        return float(rate_str.replace('kbit', '')) / 1000
    return 0


def generate_root_qdisc(spec):
    """Generate the root HTB qdisc command."""
    link = spec['link']
    root = spec['root']
    default = root['default_classid_minor']
    return (f"tc qdisc add dev {link['interface']} root handle {root['handle']} "
            f"htb default {default}")


def generate_class_commands(spec):
    """Generate tc class commands for the two-level HTB hierarchy."""
    commands = []
    iface = spec['link']['interface']
    handle = spec['root']['handle'].rstrip(':')

    for cls in spec['classes']:
        # Level 1 classes (direct children of root)
        parent = f"{handle}:{cls['parent_minor']}"
        classid = f"{handle}:{cls['classid_minor']}"
        commands.append(
            f"tc class add dev {iface} parent {parent} classid {classid} "
            f"htb rate {cls['rate']} ceil {cls['ceil']} prio {cls['prio']}")

        # Level 2 classes (children of level-1 classes)
        if 'children' in cls:
            for child in cls['children']:
                child_parent = f"{handle}:{cls['parent_minor']}"
                child_classid = f"{handle}:{child['classid_minor']}"
                commands.append(
                    f"tc class add dev {iface} parent {child_parent} "
                    f"classid {child_classid} "
                    f"htb rate {child['rate']} ceil {child['ceil']} "
                    f"prio {child['prio']}")

    return commands


def generate_filter_commands(spec):
    """Generate tc u32 filter commands for DSCP-based classification."""
    commands = []
    iface = spec['link']['interface']
    root_handle = spec['root']['handle']
    prio = 1

    for cls in spec['classes']:
        if 'children' not in cls:
            continue
        for child in cls['children']:
            if child.get('dscp'):
                handle = spec['root']['handle'].rstrip(':')
                tos_val = dscp_to_tos(child['dscp'])
                flowid = f"{handle}:{child['classid_minor']}"
                commands.append(
                    f"tc filter add dev {iface} parent {root_handle} "
                    f"protocol ip prio {prio} u32 "
                    f"match ip tos {tos_val:#04x} 0xff flowid {flowid}")
                prio += 1

    return commands


def generate_leaf_qdisc_commands(spec):
    """Generate leaf qdisc commands for each leaf class."""
    commands = []
    iface = spec['link']['interface']
    handle_num = 10

    for cls in spec['classes']:
        if 'children' not in cls:
            continue
        for child in cls['children']:
            leaf = child.get('leaf_qdisc')
            if not leaf:
                continue

            handle_prefix = spec['root']['handle'].rstrip(':')
            parent = f"{handle_prefix}:{child['classid_minor']}"

            if isinstance(leaf, str):
                commands.append(
                    f"tc qdisc add dev {iface} parent {parent} "
                    f"handle {handle_num}: {leaf}")
            elif isinstance(leaf, dict):
                qtype = leaf['type']
                params = ''
                if qtype == 'pfifo' and 'limit' in leaf:
                    params = f" limit {leaf['limit']}"
                commands.append(
                    f"tc qdisc add dev {iface} parent {parent} "
                    f"handle {handle_num}: {qtype}{params}")

            handle_num += 10

    return commands


def generate_report(spec, all_commands):
    """Generate JSON report documenting the full tc configuration."""
    handle = spec['root']['handle'].rstrip(':')
    report = {
        'interface': spec['link']['interface'],
        'link_speed': spec['link']['speed'],
        'root_qdisc': {
            'handle': spec['root']['handle'],
            'type': 'htb',
            'default_class': f"{handle}:{spec['root']['default_classid_minor']}"
        },
        'classes': [],
        'filters': [],
        'leaf_qdiscs': [],
        'tc_commands': all_commands
    }

    for cls in spec['classes']:
        report['classes'].append({
            'name': cls['name'],
            'classid': f"{handle}:{cls['classid_minor']}",
            'parent': f"{handle}:{cls['parent_minor']}",
            'rate': cls['rate'],
            'ceil': cls['ceil'],
            'prio': cls['prio'],
            'is_leaf': 'children' not in cls
        })

        if 'children' in cls:
            for child in cls['children']:
                report['classes'].append({
                    'name': child['name'],
                    'classid': f"{handle}:{child['classid_minor']}",
                    'parent': f"{handle}:{cls['classid_minor']}",
                    'rate': child['rate'],
                    'ceil': child['ceil'],
                    'prio': child['prio'],
                    'is_leaf': True,
                    'dscp': child.get('dscp')
                })

    for cls in spec['classes']:
        if 'children' not in cls:
            continue
        for child in cls['children']:
            if child.get('dscp'):
                tos = dscp_to_tos(child['dscp'])
                report['filters'].append({
                    'dscp': child['dscp'],
                    'tos_hex': f"{tos:#04x}",
                    'tos_mask': '0xfc',
                    'flowid': f"{handle}:{child['classid_minor']}",
                    'name': child['name']
                })

    for cls in spec['classes']:
        if 'children' not in cls:
            continue
        for child in cls['children']:
            leaf = child.get('leaf_qdisc')
            if leaf:
                if isinstance(leaf, str):
                    report['leaf_qdiscs'].append({
                        'parent': f"{handle}:{child['classid_minor']}",
                        'type': leaf,
                        'name': child['name']
                    })
                elif isinstance(leaf, dict):
                    entry = {
                        'parent': f"{handle}:{child['classid_minor']}",
                        'type': leaf['type'],
                        'name': child['name']
                    }
                    if 'limit' in leaf:
                        entry['limit'] = leaf['limit']
                    report['leaf_qdiscs'].append(entry)

    return report


def main():
    spec_path = os.environ.get('SPEC_PATH', '/app/bandwidth_spec.yaml')
    output_commands = '/app/tc_commands.sh'
    output_report = '/app/tc_report.json'

    spec = load_spec(spec_path)

    all_commands = []
    all_commands.append(generate_root_qdisc(spec))
    all_commands.extend(generate_class_commands(spec))
    all_commands.extend(generate_filter_commands(spec))
    all_commands.extend(generate_leaf_qdisc_commands(spec))

    with open(output_commands, 'w') as f:
        f.write("#!/bin/bash\n")
        f.write("# TC Configuration - HTB Hierarchy\n")
        f.write(f"tc qdisc del dev {spec['link']['interface']} root 2>/dev/null\n\n")
        for cmd in all_commands:
            f.write(cmd + "\n")
    os.chmod(output_commands, 0o755)

    report = generate_report(spec, all_commands)
    with open(output_report, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Generated {len(all_commands)} tc commands -> {output_commands}")
    print(f"Report -> {output_report}")


if __name__ == '__main__':
    main()
