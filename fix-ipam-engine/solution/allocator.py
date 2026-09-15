#!/usr/bin/env python3
"""
IPAM subnet allocation planner.
Reads current network state and expansion requirements,
computes valid subnet placements respecting VRF isolation,
CIDR alignment, contiguous block constraints, and exclusion zones.

"""
import json
import math
import sys

import netaddr


def load_state(path):
    """Load current network state."""
    with open(path) as f:
        return json.load(f)


def compute_available(parent_cidr, existing_in_vrf):
    """
    Compute available IP space within a parent prefix, subtracting
    all existing allocations in the same VRF that fall within the parent
    and have a more specific prefix length.
    """
    parent = netaddr.IPNetwork(parent_cidr)
    available = netaddr.IPSet([parent])
    for e in existing_in_vrf:
        # Only subtract prefixes strictly contained within parent
        if e in parent and e.prefixlen > parent.prefixlen:
            available -= netaddr.IPSet([e])
    return available


def allocate_contiguous(available, count, prefix_length, version=4):
    """
    Find the lowest-addressed CIDR-aligned contiguous block of `count`
    prefixes of given length. The block must form a single supernet.

    For count prefixes of /prefix_length, the supernet is
    /(prefix_length - log2(count)).
    """
    supernet_bits = int(math.log2(count))
    supernet_length = prefix_length - supernet_bits

    bits = 32 if version == 4 else 128
    supernet_size = 2 ** (bits - supernet_length)

    for cidr in sorted(available.iter_cidrs(), key=lambda c: c.first):
        if cidr.prefixlen > supernet_length:
            continue

        # Find first supernet-aligned boundary within this CIDR
        start = cidr.first
        if start % supernet_size != 0:
            start = ((start // supernet_size) + 1) * supernet_size

        while start + supernet_size - 1 <= cidr.last:
            candidate = netaddr.IPNetwork(
                f"{netaddr.IPAddress(start, version=version)}/{supernet_length}"
            )
            subnets = list(candidate.subnet(prefix_length))
            if len(subnets) == count:
                all_avail = all(
                    netaddr.IPSet([s]).issubset(available) for s in subnets
                )
                if all_avail:
                    return subnets
            start += supernet_size

    return None


def allocate_non_contiguous(available, count, prefix_length):
    """
    Allocate `count` non-contiguous prefixes of given length from
    available space, preferring lowest addresses (first-fit).
    """
    results = []
    remaining = available.copy()

    for cidr in sorted(remaining.iter_cidrs(), key=lambda c: c.first):
        if cidr.prefixlen > prefix_length:
            continue
        for subnet in cidr.subnet(prefix_length):
            if netaddr.IPSet([subnet]).issubset(remaining):
                results.append(subnet)
                remaining -= netaddr.IPSet([subnet])
                if len(results) == count:
                    return results

    return None


def main():
    state = load_state('/data/network_state.json')
    with open('/data/expansion.json') as f:
        expansion = json.load(f)

    # Build prefix index by VRF
    prefixes_by_vrf = {}
    for p in state['prefixes']:
        vrf = p['vrf']
        prefixes_by_vrf.setdefault(vrf, []).append(netaddr.IPNetwork(p['prefix']))

    plan = {'allocations': {}}

    for req in expansion['requests']:
        req_id = req['id']
        vrf_name = req['vrf']
        parent_cidr = req['parent']
        count = req['count']
        prefix_length = req['prefix_length']
        contiguous = req.get('contiguous', False)
        exclude = req.get('exclude', [])
        site = req.get('site', '')
        is_pool = req.get('is_pool', False)

        parent = netaddr.IPNetwork(parent_cidr)
        version = parent.version

        # Compute available space within parent for this VRF
        existing = prefixes_by_vrf.get(vrf_name, [])
        available = compute_available(parent_cidr, existing)

        # Apply exclusion zones
        for excl in exclude:
            available -= netaddr.IPSet([netaddr.IPNetwork(excl)])

        # Allocate prefixes
        if contiguous:
            networks = allocate_contiguous(available, count, prefix_length, version)
        else:
            networks = allocate_non_contiguous(available, count, prefix_length)

        if networks is None:
            raise RuntimeError(f"Cannot satisfy requirement {req_id}: "
                               f"insufficient space in {parent_cidr} (VRF: {vrf_name})")

        allocs = []
        for net in networks:
            allocs.append({
                'prefix': str(net.cidr),
                'vrf': vrf_name,
                'site': site,
                'is_pool': is_pool,
                'status': 'active'
            })
            # Track for subsequent allocations
            prefixes_by_vrf.setdefault(vrf_name, []).append(net)

        plan['allocations'][req_id] = allocs

    with open('/app/allocation_plan.json', 'w') as f:
        json.dump(plan, f, indent=2)

    total = sum(len(a) for a in plan['allocations'].values())
    print(f"Allocation plan written: {total} prefixes across {len(plan['allocations'])} requests")


if __name__ == '__main__':
    main()
