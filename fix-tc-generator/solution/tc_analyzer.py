#!/usr/bin/env python3
"""
TC Configuration Analyzer, Optimizer, and Bandwidth Simulator.

Analyzes a multi-interface HTB qdisc topology for invariant violations,
optimizes the configuration, simulates steady-state bandwidth allocation,
evaluates SLA compliance, and generates corrected tc commands with
DSCP-based u32 filter classification.
"""
import yaml
import json
import os
import copy


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def rate_to_mbit(rate_str):
    """Convert rate string (e.g., '3gbit', '1600mbit') to float mbit."""
    rate_str = str(rate_str).lower().strip()
    if rate_str.endswith('gbit'):
        return float(rate_str.replace('gbit', '')) * 1000
    elif rate_str.endswith('mbit'):
        return float(rate_str.replace('mbit', ''))
    elif rate_str.endswith('kbit'):
        return float(rate_str.replace('kbit', '')) / 1000
    return float(rate_str)


def mbit_to_rate_str(mbit):
    """Convert mbit float to human-readable rate string."""
    if mbit >= 1000 and mbit % 1000 == 0:
        return f"{int(mbit // 1000)}gbit"
    elif mbit == int(mbit):
        return f"{int(mbit)}mbit"
    else:
        return f"{mbit}mbit"


def detect_violations(topology):
    """Detect all HTB invariant violations across all interfaces."""
    violations = []

    for iface_name, iface in topology['interfaces'].items():
        default_minor = iface['root']['default_minor']
        all_leaf_minors = set()

        for parent_cls in iface['classes']:
            if 'children' in parent_cls:
                parent_rate_mbit = rate_to_mbit(parent_cls['rate'])
                parent_ceil_mbit = rate_to_mbit(parent_cls['ceil'])

                # Collect leaf minors
                for child in parent_cls['children']:
                    all_leaf_minors.add(child['minor'])

                # Check each child for rate>ceil and ceil>parent_ceil
                for child in parent_cls['children']:
                    child_rate = rate_to_mbit(child['rate'])
                    child_ceil = rate_to_mbit(child['ceil'])

                    if child_rate > child_ceil:
                        violations.append({
                            'type': 'rate_exceeds_ceil',
                            'interface': iface_name,
                            'class_name': child['name'],
                            'details': (f"rate {child_rate:.0f}mbit exceeds "
                                        f"ceil {child_ceil:.0f}mbit")
                        })

                    if child_ceil > parent_ceil_mbit:
                        violations.append({
                            'type': 'ceil_exceeds_parent_ceil',
                            'interface': iface_name,
                            'class_name': child['name'],
                            'details': (f"ceil {child_ceil:.0f}mbit exceeds "
                                        f"parent {parent_cls['name']} ceil "
                                        f"{parent_ceil_mbit:.0f}mbit")
                        })

                # Check overcommitment
                children_sum = sum(
                    rate_to_mbit(c['rate']) for c in parent_cls['children']
                )
                if children_sum > parent_rate_mbit + 0.01:
                    violations.append({
                        'type': 'overcommitted',
                        'interface': iface_name,
                        'class_name': parent_cls['name'],
                        'details': (f"children rate sum {children_sum:.0f}mbit "
                                    f"exceeds parent rate "
                                    f"{parent_rate_mbit:.0f}mbit")
                    })
            else:
                all_leaf_minors.add(parent_cls['minor'])

        # Check default class validity
        if default_minor not in all_leaf_minors:
            violations.append({
                'type': 'invalid_default',
                'interface': iface_name,
                'class_name': f"default_minor_{default_minor}",
                'details': (f"default_minor {default_minor} does not match "
                            f"any existing leaf class")
            })

    return violations


def optimize_config(topology):
    """Fix all HTB invariant violations and return optimized topology."""
    opt = copy.deepcopy(topology)

    for iface_name, iface in opt['interfaces'].items():
        for parent_cls in iface['classes']:
            if 'children' not in parent_cls:
                continue

            parent_ceil_mbit = rate_to_mbit(parent_cls['ceil'])

            # Fix rate > ceil by raising ceil to match rate
            for child in parent_cls['children']:
                child_rate = rate_to_mbit(child['rate'])
                child_ceil = rate_to_mbit(child['ceil'])
                if child_rate > child_ceil:
                    child['ceil'] = mbit_to_rate_str(child_rate)

            # Fix ceil > parent ceil by clamping
            for child in parent_cls['children']:
                child_ceil = rate_to_mbit(child['ceil'])
                if child_ceil > parent_ceil_mbit:
                    child['ceil'] = mbit_to_rate_str(parent_ceil_mbit)

            # Fix overcommitment by proportional scaling
            parent_rate_mbit = rate_to_mbit(parent_cls['rate'])
            children_sum = sum(
                rate_to_mbit(c['rate']) for c in parent_cls['children']
            )
            if children_sum > parent_rate_mbit + 0.01:
                scale = parent_rate_mbit / children_sum
                for child in parent_cls['children']:
                    new_rate = rate_to_mbit(child['rate']) * scale
                    child['rate'] = mbit_to_rate_str(new_rate)

        # Fix invalid default by selecting lowest-priority leaf
        all_leaf_info = []
        for parent_cls in iface['classes']:
            if 'children' in parent_cls:
                for child in parent_cls['children']:
                    all_leaf_info.append(
                        (parent_cls['prio'], child['prio'], child['minor'])
                    )

        leaf_minors = {info[2] for info in all_leaf_info}
        if iface['root']['default_minor'] not in leaf_minors:
            # Pick the lowest-priority leaf (highest prio numbers)
            all_leaf_info.sort(
                key=lambda x: (x[0], x[1]), reverse=True
            )
            iface['root']['default_minor'] = all_leaf_info[0][2]

    return opt


def simulate_bandwidth(opt_topology, demands):
    """
    Compute steady-state bandwidth allocation using HTB's hierarchical
    surplus lending model.

    Phase 1: Each leaf gets min(demand, rate) as guaranteed bandwidth.
    Phase 2: Intra-parent surplus distributed to children by priority.
    Phase 3: Link-level surplus distributed to parents by priority,
             then within each parent to its children by priority.
    """
    results = {}

    for iface_name, iface in opt_topology['interfaces'].items():
        link_speed = rate_to_mbit(iface['speed'])

        # Build demand map from DSCP
        demand_map = {}
        if iface_name in demands:
            for d in demands[iface_name]:
                demand_map[d['dscp']] = d['offered_rate_mbit']

        # Build parent/child structure
        parents = []
        for parent_cls in iface['classes']:
            children_data = []
            if 'children' in parent_cls:
                for child in parent_cls['children']:
                    dscp = child.get('dscp', 0)
                    children_data.append({
                        'name': child['name'],
                        'rate': rate_to_mbit(child['rate']),
                        'ceil': rate_to_mbit(child['ceil']),
                        'prio': child['prio'],
                        'demand': demand_map.get(dscp, 0),
                        'allocated': 0.0,
                    })
            parents.append({
                'name': parent_cls['name'],
                'rate': rate_to_mbit(parent_cls['rate']),
                'ceil': rate_to_mbit(parent_cls['ceil']),
                'prio': parent_cls['prio'],
                'children': children_data,
            })

        # Phase 1: Guaranteed allocation
        for parent in parents:
            for child in parent['children']:
                child['allocated'] = min(child['demand'], child['rate'])

        # Phase 2: Intra-parent surplus distribution by priority
        for parent in parents:
            parent_used = sum(c['allocated'] for c in parent['children'])
            surplus = parent['rate'] - parent_used
            if surplus <= 0:
                continue

            prio_levels = sorted(set(c['prio'] for c in parent['children']))
            for prio in prio_levels:
                if surplus <= 0.01:
                    break
                wanting = [
                    c for c in parent['children']
                    if c['prio'] == prio
                    and c['demand'] > c['allocated'] + 0.01
                    and c['ceil'] > c['allocated'] + 0.01
                ]
                if not wanting:
                    continue

                total_want = sum(
                    min(c['demand'] - c['allocated'],
                        c['ceil'] - c['allocated'])
                    for c in wanting
                )
                if total_want <= 0.01:
                    continue

                give = min(surplus, total_want)
                for c in wanting:
                    c_want = min(c['demand'] - c['allocated'],
                                c['ceil'] - c['allocated'])
                    share = give * (c_want / total_want)
                    c['allocated'] += share
                surplus -= give

        # Phase 3: Link-level surplus distribution
        total_parent_used = sum(
            sum(c['allocated'] for c in p['children']) for p in parents
        )
        link_surplus = link_speed - total_parent_used

        if link_surplus > 0.01:
            parent_prios = sorted(set(p['prio'] for p in parents))
            for pprio in parent_prios:
                if link_surplus <= 0.01:
                    break
                for parent in parents:
                    if parent['prio'] != pprio or link_surplus <= 0.01:
                        continue

                    parent_used = sum(
                        c['allocated'] for c in parent['children']
                    )
                    parent_headroom = parent['ceil'] - parent_used
                    if parent_headroom <= 0.01:
                        continue

                    children_want = sum(
                        max(0, min(c['demand'] - c['allocated'],
                                   c['ceil'] - c['allocated']))
                        for c in parent['children']
                    )
                    if children_want <= 0.01:
                        continue

                    give_to_parent = min(
                        children_want, parent_headroom, link_surplus
                    )

                    # Distribute within parent by child priority
                    remaining = give_to_parent
                    child_prios = sorted(
                        set(c['prio'] for c in parent['children'])
                    )
                    for cprio in child_prios:
                        if remaining <= 0.01:
                            break
                        wanting = [
                            c for c in parent['children']
                            if c['prio'] == cprio
                            and c['demand'] > c['allocated'] + 0.01
                            and c['ceil'] > c['allocated'] + 0.01
                        ]
                        if not wanting:
                            continue

                        total_c_want = sum(
                            min(c['demand'] - c['allocated'],
                                c['ceil'] - c['allocated'])
                            for c in wanting
                        )
                        if total_c_want <= 0.01:
                            continue

                        give = min(remaining, total_c_want)
                        for c in wanting:
                            c_want = min(c['demand'] - c['allocated'],
                                         c['ceil'] - c['allocated'])
                            share = give * (c_want / total_c_want)
                            c['allocated'] += share
                        remaining -= give

                    link_surplus -= give_to_parent

        # Collect results
        iface_alloc = {}
        for parent in parents:
            for child in parent['children']:
                demand = child['demand']
                allocated = round(child['allocated'])
                iface_alloc[child['name']] = {
                    'allocated_mbit': allocated,
                    'demand_mbit': demand,
                    'utilization': round(allocated / demand, 4)
                    if demand > 0 else 1.0,
                }

        results[iface_name] = iface_alloc

    return results


def check_sla_compliance(simulation_results, sla_requirements):
    """Evaluate SLA compliance across all classes and interfaces."""
    violations = []
    compliant = 0
    total = 0

    for iface_name, classes in simulation_results.items():
        for class_name, alloc in classes.items():
            if class_name not in sla_requirements:
                continue
            total += 1
            sla = sla_requirements[class_name]
            actual_ratio = alloc['utilization']
            required_ratio = sla['min_throughput_ratio']

            if actual_ratio >= required_ratio:
                compliant += 1
            else:
                violations.append({
                    'class_name': class_name,
                    'interface': iface_name,
                    'required_ratio': required_ratio,
                    'actual_ratio': actual_ratio,
                })

    return {
        'violations': violations,
        'compliant_count': compliant,
        'total_count': total,
    }


def build_optimized_config_report(opt_topology):
    """Build the optimized_config section of the analysis report."""
    config = {}
    for iface_name, iface in opt_topology['interfaces'].items():
        classes = []
        for parent_cls in iface['classes']:
            classes.append({
                'classid': f"1:{parent_cls['minor']}",
                'name': parent_cls['name'],
                'rate': parent_cls['rate'],
                'ceil': parent_cls['ceil'],
                'prio': parent_cls['prio'],
                'is_leaf': False,
            })
            if 'children' in parent_cls:
                for child in parent_cls['children']:
                    classes.append({
                        'classid': f"1:{child['minor']}",
                        'name': child['name'],
                        'rate': child['rate'],
                        'ceil': child['ceil'],
                        'prio': child['prio'],
                        'is_leaf': True,
                    })
        config[iface_name] = {
            'classes': classes,
            'default_minor': iface['root']['default_minor'],
        }
    return config


def generate_tc_commands(opt_topology):
    """Generate tc commands for all interfaces using the optimized config."""
    all_commands = {}

    for iface_name, iface in opt_topology['interfaces'].items():
        commands = []
        handle = iface['root']['handle']
        handle_num = handle.rstrip(':')
        default_minor = iface['root']['default_minor']

        # Delete existing qdisc
        commands.append(
            f"tc qdisc del dev {iface_name} root 2>/dev/null"
        )

        # Root HTB qdisc
        commands.append(
            f"tc qdisc add dev {iface_name} root handle {handle} "
            f"htb default {default_minor}"
        )

        # Parent classes (level 1)
        for parent_cls in iface['classes']:
            parent_id = f"{handle_num}:{parent_cls['parent_minor']}"
            classid = f"{handle_num}:{parent_cls['minor']}"
            commands.append(
                f"tc class add dev {iface_name} parent {parent_id} "
                f"classid {classid} htb rate {parent_cls['rate']} "
                f"ceil {parent_cls['ceil']} prio {parent_cls['prio']}"
            )

            # Child classes (level 2)
            if 'children' in parent_cls:
                for child in parent_cls['children']:
                    child_parent = f"{handle_num}:{parent_cls['minor']}"
                    child_classid = f"{handle_num}:{child['minor']}"
                    commands.append(
                        f"tc class add dev {iface_name} "
                        f"parent {child_parent} classid {child_classid} "
                        f"htb rate {child['rate']} ceil {child['ceil']} "
                        f"prio {child['prio']}"
                    )

        # Filters (DSCP-based u32 classification)
        filter_prio = 1
        for parent_cls in iface['classes']:
            if 'children' not in parent_cls:
                continue
            for child in parent_cls['children']:
                if 'dscp' in child:
                    dscp = child['dscp']
                    tos = dscp << 2
                    flowid = f"{handle_num}:{child['minor']}"
                    commands.append(
                        f"tc filter add dev {iface_name} parent {handle} "
                        f"protocol ip prio {filter_prio} u32 "
                        f"match ip tos {tos:#04x} 0xfc flowid {flowid}"
                    )
                    filter_prio += 1

        # Leaf qdiscs
        qdisc_handle = 10
        for parent_cls in iface['classes']:
            if 'children' not in parent_cls:
                continue
            for child in parent_cls['children']:
                leaf = child.get('leaf_qdisc')
                if not leaf:
                    continue
                parent_id = f"{handle_num}:{child['minor']}"
                if isinstance(leaf, str):
                    commands.append(
                        f"tc qdisc add dev {iface_name} parent {parent_id} "
                        f"handle {qdisc_handle}: {leaf}"
                    )
                elif isinstance(leaf, dict):
                    qtype = leaf['type']
                    params = ''
                    if 'limit' in leaf:
                        params = f" limit {leaf['limit']}"
                    commands.append(
                        f"tc qdisc add dev {iface_name} parent {parent_id} "
                        f"handle {qdisc_handle}: {qtype}{params}"
                    )
                qdisc_handle += 10

        all_commands[iface_name] = commands

    return all_commands


def main():
    topology = load_yaml('/app/topology.yaml')
    demands_data = load_yaml('/app/traffic_demands.yaml')
    sla_data = load_yaml('/app/sla_requirements.yaml')

    demands = demands_data['traffic_demands']
    sla_reqs = sla_data['sla_requirements']

    # Detect violations
    violations = detect_violations(topology)

    # Optimize configuration
    opt_topology = optimize_config(topology)

    # Simulate bandwidth allocation
    simulation = simulate_bandwidth(opt_topology, demands)

    # Check SLA compliance
    sla_compliance = check_sla_compliance(simulation, sla_reqs)

    # Build and write analysis report
    report = {
        'violations': violations,
        'optimized_config': build_optimized_config_report(opt_topology),
        'bandwidth_simulation': simulation,
        'sla_compliance': sla_compliance,
    }

    with open('/app/analysis_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    # Generate and write tc commands
    tc_commands = generate_tc_commands(opt_topology)
    with open('/app/optimized_tc_commands.sh', 'w') as f:
        f.write("#!/bin/bash\n")
        f.write("# Optimized TC Configuration for Multi-Interface HTB\n\n")
        for iface_name, commands in tc_commands.items():
            f.write(f"# --- {iface_name} ---\n")
            for cmd in commands:
                f.write(cmd + "\n")
            f.write("\n")
    os.chmod('/app/optimized_tc_commands.sh', 0o755)

    # Write validation summary
    with open('/app/validation_summary.txt', 'w') as f:
        f.write("HTB Configuration Analysis Summary\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Violations detected: {len(violations)}\n")
        for v in violations:
            f.write(f"  [{v['interface']}] {v['type']}: "
                    f"{v['class_name']} - {v['details']}\n")
        f.write(f"\nSLA Compliance: "
                f"{sla_compliance['compliant_count']}/"
                f"{sla_compliance['total_count']} classes meet SLA targets\n")
        f.write(f"SLA Violations: "
                f"{len(sla_compliance['violations'])}\n")
        for sv in sla_compliance['violations']:
            f.write(f"  [{sv['interface']}] {sv['class_name']}: "
                    f"actual {sv['actual_ratio']:.4f} < "
                    f"required {sv['required_ratio']}\n")

    print(f"Analysis complete. {len(violations)} HTB violations detected.")
    print(f"SLA compliance: {sla_compliance['compliant_count']}/"
          f"{sla_compliance['total_count']} classes meet targets.")


if __name__ == '__main__':
    main()
