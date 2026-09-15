#!/usr/bin/env python3

"""HTB Traffic Shaping Forensics Tool.

Parses raw tc, nft, and ip command output to reconstruct HTB hierarchies,
detect misconfigurations and cross-tool inconsistencies, compute
steady-state bandwidth allocations, and check SLA compliance.
"""

import json
import os
import re


def parse_rate(rate_str):
    """Convert tc rate string (e.g. '3Gbit', '500Mbit') to Mbps float."""
    m = re.match(r'(\d+(?:\.\d+)?)\s*(Gbit|Mbit|Kbit|bit)', rate_str)
    if not m:
        raise ValueError(f"Cannot parse rate: {rate_str}")
    val = float(m.group(1))
    unit = m.group(2)
    multipliers = {'Gbit': 1000.0, 'Mbit': 1.0, 'Kbit': 0.001, 'bit': 0.000001}
    return val * multipliers[unit]


def parse_tc_classes(text):
    """Parse tc -s -d class show output into list of class dicts.

    Handles multi-line blocks with statistics, burst, and token info.
    Extracts: classid, parent, rate, ceil, prio, quantum.
    """
    classes = []
    blocks = re.split(r'\n(?=class htb )', text.strip())
    for block in blocks:
        block = block.strip()
        if not block.startswith('class htb '):
            continue
        first_line = block.split('\n')[0]

        # Extract classid and parent/root
        m = re.match(r'class htb (\S+)\s+(root|parent\s+(\S+))', first_line)
        if not m:
            continue
        classid = m.group(1)
        is_root = m.group(2).strip() == 'root'
        parent = m.group(3) if m.group(3) else None

        # Extract rate (handles Gbit/Mbit/Kbit)
        rate_m = re.search(r'\brate\s+(\d+(?:\.\d+)?(?:Gbit|Mbit|Kbit|bit))\b', first_line)
        ceil_m = re.search(r'\bceil\s+(\d+(?:\.\d+)?(?:Gbit|Mbit|Kbit|bit))\b', first_line)
        rate_mbps = parse_rate(rate_m.group(1)) if rate_m else 0.0
        ceil_mbps = parse_rate(ceil_m.group(1)) if ceil_m else rate_mbps

        # Extract prio and quantum (absent for root class)
        prio_m = re.search(r'\bprio\s+(\d+)', first_line)
        quantum_m = re.search(r'\bquantum\s+(\d+)', first_line)
        prio = int(prio_m.group(1)) if prio_m else 0
        quantum = int(quantum_m.group(1)) if quantum_m else 1500

        classes.append({
            'classid': classid,
            'parent': parent,
            'is_root': is_root,
            'rate_mbps': rate_mbps,
            'ceil_mbps': ceil_mbps,
            'prio': prio,
            'quantum': quantum,
        })
    return classes


def parse_tc_qdisc(text):
    """Parse tc -s -d qdisc show output.

    Returns (handle, default_class_id) where default is decoded from hex.
    """
    m = re.search(r'qdisc htb (\S+)\s+root.*?default\s+(0x[0-9a-fA-F]+)', text)
    if not m:
        return None, None
    handle = m.group(1)
    default_minor = int(m.group(2), 16)
    major = handle.rstrip(':')
    return handle, f"{major}:{default_minor}"


def parse_tc_filters(text):
    """Parse tc -s -d filter show output (fw type).

    Returns dict mapping normalized hex mark -> classid.
    """
    result = {}
    for line in text.split('\n'):
        m = re.search(r'handle\s+(0x[0-9a-fA-F]+)\s+classid\s+(\S+)', line)
        if m:
            mark = hex(int(m.group(1), 16))
            result[mark] = m.group(2)
    return result


def parse_nft_ruleset(text):
    """Parse nft list ruleset output.

    Returns dict mapping output interface -> list of normalized hex fwmarks.
    """
    per_iface = {}
    for line in text.split('\n'):
        m = re.search(
            r'oifname\s+"([^"]+)".*meta\s+mark\s+set\s+(0x[0-9a-fA-F]+)', line
        )
        if m:
            iface = m.group(1)
            mark = hex(int(m.group(2), 16))
            per_iface.setdefault(iface, []).append(mark)
    return per_iface


def validate_interface(classes, qdisc_handle, default_class, tc_filters,
                       iface, nft_marks):
    """Validate tc hierarchy and cross-tool consistency for one interface."""
    errors = []
    by_id = {c['classid']: c for c in classes}

    # 1. Orphan classes: parent references nonexistent class/qdisc
    for c in classes:
        if c['is_root']:
            continue
        p = c['parent']
        if p != qdisc_handle and p not in by_id:
            errors.append({
                'type': 'orphan_class',
                'interface': iface,
                'class': c['classid'],
                'details': f"Parent {p} does not exist in the hierarchy",
            })

    # 2. Ceil exceeds parent ceil
    for c in classes:
        if c['is_root'] or c['parent'] not in by_id:
            continue
        parent = by_id[c['parent']]
        if c['ceil_mbps'] > parent['ceil_mbps']:
            errors.append({
                'type': 'ceil_exceeds_parent',
                'interface': iface,
                'class': c['classid'],
                'details': (
                    f"ceil {c['ceil_mbps']} Mbps exceeds parent "
                    f"{c['parent']} ceil {parent['ceil_mbps']} Mbps"
                ),
            })

    # 3. Rate oversubscription: children sum > parent rate
    children_of = {}
    for c in classes:
        if c['is_root']:
            continue
        p = c['parent']
        if p == qdisc_handle or p in by_id:
            children_of.setdefault(p, []).append(c)

    for parent_id, child_list in children_of.items():
        if parent_id in by_id:
            parent = by_id[parent_id]
            total_child_rate = sum(ch['rate_mbps'] for ch in child_list)
            if total_child_rate > parent['rate_mbps']:
                errors.append({
                    'type': 'rate_oversubscription',
                    'interface': iface,
                    'class': parent_id,
                    'details': (
                        f"Children rates sum {total_child_rate} Mbps exceeds "
                        f"parent rate {parent['rate_mbps']} Mbps"
                    ),
                })

    # 4. Missing default class
    if default_class and default_class not in by_id:
        errors.append({
            'type': 'missing_default_class',
            'interface': iface,
            'qdisc': qdisc_handle,
            'class': default_class,
            'details': f"Default class {default_class} does not exist",
        })

    # 5. Invalid filter targets (classid referenced by filter doesn't exist)
    for mark, classid in tc_filters.items():
        if classid not in by_id:
            errors.append({
                'type': 'invalid_filter_target',
                'interface': iface,
                'filter_handle': mark,
                'class': classid,
                'details': f"Filter target class {classid} does not exist",
            })

    # 6. Cross-tool: nft sets mark for this interface but no tc fw filter matches
    for mark in set(nft_marks):
        if mark not in tc_filters:
            errors.append({
                'type': 'nft_mark_no_tc_filter',
                'interface': iface,
                'mark': mark,
                'details': (
                    f"nftables sets mark {mark} for {iface} traffic but "
                    f"no tc fw filter for this mark exists on {iface}"
                ),
            })

    return errors


def compute_leaf_allocations(cls, available_bw, children_map):
    """Recursively compute leaf bandwidth using kernel HTB semantics.

    Algorithm:
    1. effective_bw = min(available_bw, cls.ceil)
    2. If leaf: return effective_bw
    3. Phase 1 - guaranteed rates by priority order, with quantum-proportional
       fallback under oversubscription
    4. Phase 2 - excess bandwidth via quantum-weighted water-filling to ceil
    5. Recurse into children
    """
    classid = cls['classid']
    effective_bw = min(available_bw, cls['ceil_mbps'])

    children = children_map.get(classid, [])
    if not children:
        return {classid: effective_bw}

    # Group children by priority level
    by_prio = {}
    for child in children:
        by_prio.setdefault(child['prio'], []).append(child)

    alloc = {ch['classid']: 0.0 for ch in children}
    remaining = effective_bw
    oversubscribed = False

    # Phase 1: Guaranteed rate allocation (priority order)
    for prio in sorted(by_prio.keys()):
        group = by_prio[prio]
        total_rate = sum(c['rate_mbps'] for c in group)

        if total_rate <= remaining:
            for c in group:
                alloc[c['classid']] = float(c['rate_mbps'])
            remaining -= total_rate
        else:
            # Oversubscription: distribute by quantum ratio
            total_q = sum(c['quantum'] for c in group)
            for c in group:
                alloc[c['classid']] = remaining * c['quantum'] / total_q
            remaining = 0.0
            oversubscribed = True
            # Lower-priority children get nothing
            for lp in sorted(by_prio.keys()):
                if lp > prio:
                    for c in by_prio[lp]:
                        alloc[c['classid']] = 0.0
            break

    # Phase 2: Excess bandwidth distribution (water-filling)
    if not oversubscribed and remaining > 0.001:
        for prio in sorted(by_prio.keys()):
            if remaining <= 0.001:
                break
            group = by_prio[prio]

            for _ in range(200):
                if remaining <= 0.001:
                    break
                active = [
                    c for c in group
                    if alloc[c['classid']] < c['ceil_mbps'] - 0.001
                ]
                if not active:
                    break
                total_q = sum(c['quantum'] for c in active)
                given = 0.0
                for c in active:
                    fair_share = remaining * c['quantum'] / total_q
                    room = c['ceil_mbps'] - alloc[c['classid']]
                    actual = min(fair_share, room)
                    alloc[c['classid']] += actual
                    given += actual
                remaining -= given
                if given < 0.001:
                    break

    # Recurse into children
    result = {}
    for child in children:
        child_bw = min(alloc[child['classid']], child['ceil_mbps'])
        sub = compute_leaf_allocations(child, child_bw, children_map)
        result.update(sub)
    return result


def main():
    captures_dir = '/app/captures'

    # Load and parse per-interface tc dumps
    interfaces = {}
    for iface in ['eth0', 'eth1']:
        prefix = os.path.join(captures_dir, f'{iface}_')

        with open(f'{prefix}qdisc.txt') as f:
            qdisc_handle, default_class = parse_tc_qdisc(f.read())
        with open(f'{prefix}class.txt') as f:
            classes = parse_tc_classes(f.read())
        with open(f'{prefix}filter.txt') as f:
            filters = parse_tc_filters(f.read())

        interfaces[iface] = {
            'qdisc_handle': qdisc_handle,
            'default_class': default_class,
            'classes': classes,
            'filters': filters,
        }

    # Parse nft ruleset for per-interface mark assignments
    with open(os.path.join(captures_dir, 'nft_ruleset.txt')) as f:
        nft_per_iface = parse_nft_ruleset(f.read())

    # Validate all interfaces
    all_errors = []
    for iface, data in interfaces.items():
        nft_marks = nft_per_iface.get(iface, [])
        errs = validate_interface(
            data['classes'], data['qdisc_handle'], data['default_class'],
            data['filters'], iface, nft_marks,
        )
        all_errors.extend(errs)

    # Compute leaf bandwidth allocations per interface
    leaf_allocations = {}
    for iface, data in interfaces.items():
        classes = data['classes']
        by_id = {c['classid']: c for c in classes}
        handle = data['qdisc_handle']

        # Build children map excluding orphan classes
        children_map = {}
        for c in classes:
            if c['is_root']:
                children_map.setdefault(handle, []).append(c)
            elif c['parent'] == handle or c['parent'] in by_id:
                children_map.setdefault(c['parent'], []).append(c)

        root_classes = children_map.get(handle, [])
        if not root_classes:
            continue
        root = root_classes[0]

        raw = compute_leaf_allocations(root, root['rate_mbps'], children_map)
        leaf_allocations[iface] = {k: round(v, 2) for k, v in raw.items()}

    # Check SLA requirements
    with open('/app/sla_requirements.json') as f:
        sla = json.load(f)

    sla_violations = []
    for req in sla['requirements']:
        actual = leaf_allocations.get(req['interface'], {}).get(req['class_id'], 0.0)
        if actual < req['min_bandwidth_mbps']:
            sla_violations.append({
                'class': req['class_id'],
                'interface': req['interface'],
                'required_mbps': req['min_bandwidth_mbps'],
                'actual_mbps': actual,
            })

    # Build nft mark map: per-interface mapping of nft marks to tc classes
    nft_mark_map = {}
    for iface, data in interfaces.items():
        nft_marks = nft_per_iface.get(iface, [])
        iface_map = {}
        for mark in set(nft_marks):
            if mark in data['filters']:
                iface_map[mark] = data['filters'][mark]
        nft_mark_map[iface] = iface_map

    # Write report
    report = {
        'validation_errors': all_errors,
        'leaf_allocations': leaf_allocations,
        'sla_violations': sla_violations,
        'nft_mark_map': nft_mark_map,
    }

    with open('/app/forensic_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(
        f"Forensic analysis complete: {len(all_errors)} errors, "
        f"{len(sla_violations)} SLA violations."
    )


if __name__ == '__main__':
    main()
