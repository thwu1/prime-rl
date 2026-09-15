#!/usr/bin/env python3
"""
Diagnose and repair OSPF misconfigurations in the multi-area FRR topology.

Reads each router's FRR config, identifies protocol-level issues by
cross-referencing neighbor parameters, and applies targeted text edits.
"""

import re
import json
import ipaddress
import os

CONFIGS = '/app/configs'
TOPO = '/app/topology.json'


def load_topo():
    with open(TOPO) as f:
        return json.load(f)


def read_cfg(router):
    with open(os.path.join(CONFIGS, f'{router}.conf')) as f:
        return f.read()


def write_cfg(router, text):
    with open(os.path.join(CONFIGS, f'{router}.conf'), 'w') as f:
        f.write(text)


def get_dead_interval(cfg_text, iface):
    m = re.search(
        rf'^interface\s+{re.escape(iface)}\n((?:[ \t]+.*\n)*)',
        cfg_text, re.M)
    if m:
        d = re.search(r'ip ospf dead-interval\s+(\d+)', m.group(1))
        if d:
            return int(d.group(1))
    return 40  # OSPF default


def interface_has_ospf(cfg_text, iface_ip):
    for m in re.finditer(r'network\s+(\S+)\s+area\s+(\d+)', cfg_text):
        net = ipaddress.ip_network(m.group(1), strict=False)
        if ipaddress.ip_address(iface_ip) in net:
            return True
    return False


def get_area_type(cfg_text, area_id):
    m = re.search(rf'area\s+{area_id}\s+(stub|nssa)', cfg_text)
    return m.group(1) if m else 'normal'


def main():
    topo = load_topo()
    fixes = []

    # ── Check every link for adjacency-blocking issues ──
    for link in topo['links']:
        r1, r2 = link['endpoints']
        cfg1 = read_cfg(r1)
        cfg2 = read_cfg(r2)
        ip1 = link['interfaces'][r1]['ip']
        ip2 = link['interfaces'][r2]['ip']
        iface1 = link['interfaces'][r1]['name']
        iface2 = link['interfaces'][r2]['name']
        subnet = link['subnet']

        # Issue: interface not covered by any OSPF network statement
        for router, cfg, ip in [(r1, cfg1, ip1), (r2, cfg2, ip2)]:
            if not interface_has_ospf(cfg, ip):
                # Determine correct area from the peer's config
                peer = r2 if router == r1 else r1
                peer_cfg = read_cfg(peer)
                peer_ip = ip2 if router == r1 else ip1
                area = None
                for m in re.finditer(r'network\s+(\S+)\s+area\s+(\d+)',
                                     peer_cfg):
                    net = ipaddress.ip_network(m.group(1), strict=False)
                    if ipaddress.ip_address(peer_ip) in net:
                        area = int(m.group(2))
                        break
                if area is None:
                    # Infer area from peer's other network statements
                    # (the peer must be in some area for this link)
                    r_desc = topo['routers'].get(router, {}).get(
                        'description', '')
                    if 'Area 1' in r_desc:
                        area = 1
                    elif 'Area 2' in r_desc:
                        area = 2
                    else:
                        area = 0

                new_line = f' network {subnet} area {area}\n'
                cfg = cfg.replace('exit\n!',
                                  new_line + 'exit\n!', 1)
                # Must insert inside the router ospf block
                # Find the last 'exit' inside router ospf
                ospf = re.search(
                    r'(router ospf\n(?:[ \t]+.*\n)*)(exit\n)',
                    cfg)
                if ospf:
                    old = ospf.group(0)
                    patched = ospf.group(1) + new_line + ospf.group(2)
                    cfg = cfg.replace(old, patched, 1)

                write_cfg(router, cfg)
                fixes.append(
                    f'{router}: added network {subnet} area {area}')

        # Re-read after possible edits
        cfg1 = read_cfg(r1)
        cfg2 = read_cfg(r2)

        # Issue: dead-interval mismatch
        d1 = get_dead_interval(cfg1, iface1)
        d2 = get_dead_interval(cfg2, iface2)
        if d1 != d2:
            # Remove any non-default explicit dead-interval
            for router, iface, cfg, dval in [
                (r1, iface1, cfg1, d1), (r2, iface2, cfg2, d2)
            ]:
                if dval != 40:
                    cfg = re.sub(
                        r'[ \t]+ip ospf dead-interval \d+\n', '', cfg)
                    write_cfg(router, cfg)
                    fixes.append(
                        f'{router}: removed dead-interval {dval} on {iface}')

        # Re-read
        cfg1 = read_cfg(r1)
        cfg2 = read_cfg(r2)

        # Issue: area type mismatch (stub vs nssa)
        # Determine which area this link belongs to
        area_id = None
        for m in re.finditer(r'network\s+(\S+)\s+area\s+(\d+)', cfg1):
            net = ipaddress.ip_network(m.group(1), strict=False)
            if ipaddress.ip_address(ip1) in net:
                area_id = int(m.group(2))
                break
        if area_id is not None and area_id > 0:
            t1 = get_area_type(cfg1, area_id)
            t2 = get_area_type(cfg2, area_id)
            if t1 != t2:
                # Determine correct type from topology descriptions
                r3_desc = topo['routers'].get('R3', {}).get(
                    'description', '')
                if 'NSSA' in r3_desc and area_id == 2:
                    correct = 'nssa'
                else:
                    correct = t1 if t1 != 'normal' else t2

                for router, cfg, at in [
                    (r1, cfg1, t1), (r2, cfg2, t2)
                ]:
                    if at != correct:
                        cfg = cfg.replace(
                            f'area {area_id} {at}',
                            f'area {area_id} {correct}')
                        write_cfg(router, cfg)
                        fixes.append(
                            f'{router}: area {area_id} {at} -> {correct}')

    # ── Check external route redistribution ──
    for ext in topo.get('external_routes', []):
        origin = ext['origin']
        prefix = ext['prefix']
        cfg = read_cfg(origin)

        # Find route-map used for redistribution
        rm_m = re.search(r'redistribute static route-map\s+(\S+)', cfg)
        if not rm_m:
            continue
        rm_name = rm_m.group(1)

        # Find prefix-list referenced by the route-map
        rm_body = re.search(
            rf'^route-map\s+{re.escape(rm_name)}\s+permit\s+\d+\n'
            r'((?:[ \t]+.*\n)*)',
            cfg, re.M)
        if not rm_body:
            continue
        pl_m = re.search(r'match ip address prefix-list\s+(\S+)',
                         rm_body.group(1))
        if not pl_m:
            continue
        pl_name = pl_m.group(1)

        # Collect existing prefix-list entries
        entries = re.findall(
            rf'^ip prefix-list\s+{re.escape(pl_name)}\s+seq\s+(\d+)'
            r'\s+(permit|deny)\s+(\S+)',
            cfg, re.M)

        target_net = ipaddress.ip_network(prefix, strict=False)
        already_permitted = any(
            ipaddress.ip_network(p, strict=False) == target_net
            and a == 'permit'
            for _, a, p in entries
        )

        if not already_permitted:
            max_seq = max(int(s) for s, _, _ in entries) if entries else 0
            new_seq = max_seq + 10
            last_entry = entries[-1] if entries else None
            if last_entry:
                last_line = (
                    f'ip prefix-list {pl_name} seq {last_entry[0]} '
                    f'{last_entry[1]} {last_entry[2]}')
                new_line = (
                    f'ip prefix-list {pl_name} seq {new_seq} '
                    f'permit {prefix}')
                cfg = cfg.replace(last_line, last_line + '\n' + new_line)
            write_cfg(origin, cfg)
            fixes.append(
                f'{origin}: added prefix-list entry for {prefix}')

    print('=== OSPF Configuration Repair ===')
    if fixes:
        print(f'Applied {len(fixes)} fix(es):')
        for f in fixes:
            print(f'  - {f}')
    else:
        print('No fixes needed.')


if __name__ == '__main__':
    main()
