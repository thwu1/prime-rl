#!/usr/bin/env python3
"""
IPAM allocation engine - processes a network design specification
and produces an allocation plan with prefix hierarchy, IP assignments,
and utilization metrics.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ipam.engine import IPAMEngine
from ipam.models import Prefix, VRF


def process_design(design_file, output_file):
    """Process a network design and produce an allocation plan."""
    with open(design_file) as f:
        design = json.load(f)

    engine = IPAMEngine()

    # Create VRFs
    vrfs = {}
    for vrf_spec in design['vrfs']:
        vrf = VRF(name=vrf_spec['name'], rd=vrf_spec.get('rd'))
        vrfs[vrf.name] = vrf
        engine.vrfs.append(vrf)

    # Process allocations
    for alloc in design['allocations']:
        vrf = vrfs.get(alloc['vrf'])
        prefix = Prefix(
            prefix=alloc['prefix'],
            vrf=vrf,
            status=alloc.get('status', 'active'),
            is_pool=alloc.get('is_pool', False),
            site=alloc.get('site')
        )
        engine.add_prefix(prefix)

        # Allocate IPs for leaf prefixes
        num_ips = alloc.get('allocate_ips', 0)
        for _ in range(num_ips):
            engine.allocate_next_ip(prefix)

        # Process children
        if 'children' in alloc:
            for child_spec in alloc['children']:
                child = Prefix(
                    prefix=child_spec['prefix'],
                    vrf=vrf,
                    status=child_spec.get('status', 'active'),
                    is_pool=child_spec.get('is_pool', False),
                    site=alloc.get('site')
                )
                engine.add_prefix(child)

                num_child_ips = child_spec.get('allocate_ips', 0)
                for _ in range(num_child_ips):
                    engine.allocate_next_ip(child)

    # Rebuild hierarchy
    engine.rebuild_hierarchy()

    # Generate output
    output = {
        'prefixes': [],
        'ip_addresses': [],
        'utilization': []
    }

    for p in engine.prefixes:
        output['prefixes'].append({
            'prefix': str(p.prefix),
            'vrf': p.vrf.name if p.vrf else None,
            'status': p.status,
            'is_pool': p.is_pool,
            'depth': p._depth,
            'children': p._children,
            'site': p.site
        })

        output['utilization'].append({
            'prefix': str(p.prefix),
            'vrf': p.vrf.name if p.vrf else None,
            'utilization': round(engine.get_prefix_utilization(p), 6)
        })

    for ip in engine.ip_addresses:
        output['ip_addresses'].append({
            'address': str(ip.address),
            'vrf': ip.vrf.name if ip.vrf else None
        })

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    return output


if __name__ == '__main__':
    design_file = sys.argv[1] if len(sys.argv) > 1 else '/app/design.json'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/app/output.json'
    process_design(design_file, output_file)
