#!/usr/bin/env python3
"""
Enhanced OSPF Configuration Validator for FRRouting (FRR) multi-area topologies.

Validates:
- Adjacency formation (area assignment, timer/type consistency)
- Area type configuration (normal, stub, totally_stub, nssa)
- Route summarization (area range statements at ABRs)
- OSPF cost overrides on interfaces
- External route redistribution and visibility
- Totally stub area isolation (external routes blocked)

Usage:
    python3 ospf_checker.py [--json]
"""

import os
import re
import sys
import json
import ipaddress
from collections import defaultdict

DEFAULT_HELLO = 10
DEFAULT_DEAD = 40
DEFAULT_COST = 10


def parse_frr_config(filepath):
    """Parse an FRR configuration file into structured data."""
    with open(filepath) as f:
        content = f.read()

    config = {
        'hostname': '',
        'router_id': '',
        'interfaces': {},
        'networks': [],
        'areas': {},
        'area_ranges': [],
        'redistribute': [],
        'prefix_lists': {},
        'route_maps': {},
        'static_routes': [],
    }

    m = re.search(r'^hostname\s+(\S+)', content, re.M)
    if m:
        config['hostname'] = m.group(1)

    # Parse interface blocks
    for m in re.finditer(r'^interface\s+(\S+)\n((?:[ \t]+.*\n)*)', content, re.M):
        iface_name = m.group(1)
        body = m.group(2)
        iface_cfg = {}
        d = re.search(r'ip ospf dead-interval\s+(\d+)', body)
        if d:
            iface_cfg['dead_interval'] = int(d.group(1))
        h = re.search(r'ip ospf hello-interval\s+(\d+)', body)
        if h:
            iface_cfg['hello_interval'] = int(h.group(1))
        c = re.search(r'ip ospf cost\s+(\d+)', body)
        if c:
            iface_cfg['cost'] = int(c.group(1))
        config['interfaces'][iface_name] = iface_cfg

    # Parse router ospf block
    ospf_m = re.search(r'^router ospf\n((?:[ \t]+.*\n)*)', content, re.M)
    if ospf_m:
        ospf_body = ospf_m.group(1)

        rid = re.search(r'ospf router-id\s+(\S+)', ospf_body)
        if rid:
            config['router_id'] = rid.group(1)

        for n in re.finditer(r'network\s+(\S+)\s+area\s+(\d+)', ospf_body):
            config['networks'].append({
                'prefix': n.group(1),
                'area': int(n.group(2))
            })

        # Parse area types: check totally_stub (stub no-summary) first
        for a in re.finditer(r'area\s+(\d+)\s+stub\s+no-summary', ospf_body):
            config['areas'][int(a.group(1))] = 'totally_stub'
        for a in re.finditer(r'area\s+(\d+)\s+stub(?!\s+no-summary)', ospf_body):
            area_id = int(a.group(1))
            if area_id not in config['areas']:
                config['areas'][area_id] = 'stub'
        for a in re.finditer(r'area\s+(\d+)\s+nssa', ospf_body):
            config['areas'][int(a.group(1))] = 'nssa'

        # Parse area range (summarization) statements
        for ar in re.finditer(r'area\s+(\d+)\s+range\s+(\S+)', ospf_body):
            config['area_ranges'].append({
                'area': int(ar.group(1)),
                'range': ar.group(2)
            })

        # Parse redistribute statements
        for rd in re.finditer(
                r'redistribute\s+(\S+)(?:\s+route-map\s+(\S+))?', ospf_body):
            entry = {'protocol': rd.group(1)}
            if rd.group(2):
                entry['route_map'] = rd.group(2)
            config['redistribute'].append(entry)

    # Parse prefix-lists
    for p in re.finditer(
            r'^ip prefix-list\s+(\S+)\s+seq\s+(\d+)\s+(permit|deny)\s+(\S+)',
            content, re.M):
        name = p.group(1)
        if name not in config['prefix_lists']:
            config['prefix_lists'][name] = []
        config['prefix_lists'][name].append({
            'seq': int(p.group(2)),
            'action': p.group(3),
            'prefix': p.group(4)
        })
    for name in config['prefix_lists']:
        config['prefix_lists'][name].sort(key=lambda x: x['seq'])

    # Parse route-maps
    for rm in re.finditer(
            r'^route-map\s+(\S+)\s+(permit|deny)\s+(\d+)\n((?:[ \t]+.*\n)*)',
            content, re.M):
        name = rm.group(1)
        if name not in config['route_maps']:
            config['route_maps'][name] = []
        body = rm.group(4)
        entry = {
            'seq': int(rm.group(3)),
            'action': rm.group(2),
            'match_prefix_list': None
        }
        mp = re.search(r'match ip address prefix-list\s+(\S+)', body)
        if mp:
            entry['match_prefix_list'] = mp.group(1)
        config['route_maps'][name].append(entry)

    # Parse static routes
    for sr in re.finditer(r'^ip route\s+(\S+)\s+(\S+)', content, re.M):
        config['static_routes'].append({
            'prefix': sr.group(1),
            'nexthop': sr.group(2)
        })

    return config


def get_interface_area(config, iface_ip):
    """Determine which OSPF area an interface belongs to based on its IP."""
    ip_obj = ipaddress.ip_address(iface_ip)
    for net in config['networks']:
        net_obj = ipaddress.ip_network(net['prefix'], strict=False)
        if ip_obj in net_obj:
            return net['area']
    return None


def get_area_type(config, area_id):
    """Return the area type configured on a router for a given area."""
    return config['areas'].get(area_id, 'normal')


def get_dead_interval(config, iface_name):
    """Return the dead interval for an interface (default 40)."""
    if iface_name in config['interfaces']:
        return config['interfaces'][iface_name].get('dead_interval',
                                                     DEFAULT_DEAD)
    return DEFAULT_DEAD


def get_hello_interval(config, iface_name):
    """Return the hello interval for an interface (default 10)."""
    if iface_name in config['interfaces']:
        return config['interfaces'][iface_name].get('hello_interval',
                                                     DEFAULT_HELLO)
    return DEFAULT_HELLO


def get_ospf_cost(config, iface_name):
    """Return the OSPF cost for an interface (default 10)."""
    if iface_name in config['interfaces']:
        return config['interfaces'][iface_name].get('cost', DEFAULT_COST)
    return DEFAULT_COST


def area_types_compatible(type1, type2):
    """Check if two area type configs are compatible for adjacency formation.

    In OSPF, stub and totally_stub both set E-bit=0 in Hello packets,
    so they are compatible for forming adjacencies.
    """
    stub_set = {'stub', 'totally_stub'}
    if type1 in stub_set and type2 in stub_set:
        return True
    return type1 == type2


def prefix_list_permits(prefix_lists, pl_name, route_prefix):
    """Check whether a prefix-list permits a given route prefix."""
    if pl_name not in prefix_lists:
        return True
    check_net = ipaddress.ip_network(route_prefix, strict=False)
    for entry in prefix_lists[pl_name]:
        entry_net = ipaddress.ip_network(entry['prefix'], strict=False)
        if check_net == entry_net:
            return entry['action'] == 'permit'
    return False  # implicit deny


def route_map_permits(route_maps, prefix_lists, rm_name, route_prefix):
    """Check whether a route-map permits a given route prefix."""
    if rm_name not in route_maps:
        return True
    for entry in sorted(route_maps[rm_name], key=lambda e: e['seq']):
        if entry['match_prefix_list']:
            if prefix_list_permits(prefix_lists, entry['match_prefix_list'],
                                   route_prefix):
                return entry['action'] == 'permit'
        else:
            return entry['action'] == 'permit'
    return False  # implicit deny


class OSPFValidator:
    """Validates a multi-area OSPF design from FRR configuration files."""

    def __init__(self, configs_dir, topology_file=None):
        self.configs = {}
        self.adjacencies = {}

        topo_path = topology_file or '/app/topology.json'
        with open(topo_path) as f:
            self.topology = json.load(f)

        for fname in sorted(os.listdir(configs_dir)):
            if fname.endswith('.conf'):
                router = fname.replace('.conf', '')
                self.configs[router] = parse_frr_config(
                    os.path.join(configs_dir, fname))

    # ------------------------------------------------------------------
    def _check_link_adjacency(self, link):
        """Check whether an OSPF adjacency can form on a single link."""
        r1, r2 = link['endpoints']
        iface1_info = link['interfaces'][r1]
        iface2_info = link['interfaces'][r2]
        iface1_name = iface1_info['name']
        iface2_name = iface2_info['name']
        iface1_ip = iface1_info['ip']
        iface2_ip = iface2_info['ip']

        cfg1 = self.configs.get(r1)
        cfg2 = self.configs.get(r2)
        if not cfg1 or not cfg2:
            return {'status': 'ERROR', 'reason': 'Missing router config'}

        area1 = get_interface_area(cfg1, iface1_ip)
        area2 = get_interface_area(cfg2, iface2_ip)

        if area1 is None:
            return {'status': 'DOWN',
                    'reason': f'{r1} interface {iface1_name} not in any OSPF area'}
        if area2 is None:
            return {'status': 'DOWN',
                    'reason': f'{r2} interface {iface2_name} not in any OSPF area'}

        if area1 != area2:
            return {'status': 'DOWN',
                    'reason': f'Area ID mismatch ({area1} vs {area2})'}

        area_id = area1
        type1 = get_area_type(cfg1, area_id)
        type2 = get_area_type(cfg2, area_id)
        if not area_types_compatible(type1, type2):
            return {'status': 'DOWN',
                    'reason': (f'Area {area_id} type conflict '
                               f'({r1}={type1}, {r2}={type2})')}

        dead1 = get_dead_interval(cfg1, iface1_name)
        dead2 = get_dead_interval(cfg2, iface2_name)
        if dead1 != dead2:
            return {'status': 'DOWN',
                    'reason': (f'Dead-interval mismatch on link '
                               f'({r1}={dead1}s, {r2}={dead2}s)')}

        hello1 = get_hello_interval(cfg1, iface1_name)
        hello2 = get_hello_interval(cfg2, iface2_name)
        if hello1 != hello2:
            return {'status': 'DOWN',
                    'reason': (f'Hello-interval mismatch on link '
                               f'({r1}={hello1}s, {r2}={hello2}s)')}

        return {'status': 'FULL', 'area': area_id, 'area_type': type1}

    # ------------------------------------------------------------------
    def validate_adjacencies(self):
        """Validate all link adjacencies."""
        results = {}
        for link in self.topology['links']:
            key = f"{link['endpoints'][0]}-{link['endpoints'][1]}"
            results[key] = self._check_link_adjacency(link)
        self.adjacencies = results
        return results

    # ------------------------------------------------------------------
    def check_area_types(self):
        """Validate area type configuration against requirements."""
        reqs = self.topology.get('requirements', {}).get('area_types', {})
        results = {}

        for area_str, expected in reqs.items():
            area_id = int(area_str)
            area_result = {'expected': expected, 'routers': {}}

            for router, cfg in self.configs.items():
                has_area = any(n['area'] == area_id for n in cfg['networks'])
                if not has_area:
                    continue

                actual = get_area_type(cfg, area_id)

                if expected == 'totally_stub':
                    areas_on_router = set(n['area'] for n in cfg['networks'])
                    is_abr = len(areas_on_router) > 1
                    if is_abr:
                        correct = (actual == 'totally_stub')
                    else:
                        correct = (actual in ('stub', 'totally_stub'))
                else:
                    correct = (actual == expected)

                area_result['routers'][router] = {
                    'configured': actual,
                    'correct': correct
                }

            results[area_str] = area_result

        return results

    # ------------------------------------------------------------------
    def check_summarization(self):
        """Validate area range summarization statements on ABRs."""
        reqs = self.topology.get('requirements', {}).get('summarization', [])
        results = {}

        for req in reqs:
            router = req['router']
            area = req['area']
            expected_range = req['range']
            key = f"{router}_area{area}_{expected_range}"

            cfg = self.configs.get(router)
            if not cfg:
                results[key] = {'present': False, 'reason': 'Config missing'}
                continue

            found = any(
                ar['area'] == area and
                ipaddress.ip_network(ar['range'], strict=False) ==
                ipaddress.ip_network(expected_range, strict=False)
                for ar in cfg['area_ranges']
            )

            results[key] = {'present': found}

        return results

    # ------------------------------------------------------------------
    def check_costs(self):
        """Validate OSPF cost overrides on interfaces."""
        reqs = self.topology.get('requirements', {}).get('cost_overrides', [])
        results = {}

        for req in reqs:
            router = req['router']
            iface = req['interface']
            expected_cost = req['cost']
            key = f"{router}_{iface}"

            cfg = self.configs.get(router)
            if not cfg:
                results[key] = {
                    'expected': expected_cost, 'actual': None, 'correct': False}
                continue

            actual_cost = get_ospf_cost(cfg, iface)
            results[key] = {
                'expected': expected_cost,
                'actual': actual_cost,
                'correct': actual_cost == expected_cost
            }

        return results

    # ------------------------------------------------------------------
    def compute_reachability(self):
        """Check all-pairs reachability through formed adjacencies.

        Uses BFS over the adjacency graph. In a correctly configured OSPF
        network with all adjacencies FULL, all routers can reach each other
        (totally stub routers use default route via ABR).
        """
        adj_graph = defaultdict(set)
        for link in self.topology['links']:
            key = f"{link['endpoints'][0]}-{link['endpoints'][1]}"
            adj = self.adjacencies.get(key, {})
            if adj.get('status') == 'FULL':
                r1, r2 = link['endpoints']
                adj_graph[r1].add(r2)
                adj_graph[r2].add(r1)

        reach_sets = {}
        for src in sorted(self.configs.keys()):
            visited = set()
            queue = [src]
            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                for nbr in adj_graph[cur]:
                    if nbr not in visited:
                        queue.append(nbr)
            reach_sets[src] = visited

        reach = {}
        for src in sorted(self.configs.keys()):
            for dst in sorted(self.configs.keys()):
                if src == dst:
                    continue
                reach[f"{src}->{dst}"] = dst in reach_sets.get(src, set())

        return reach

    # ------------------------------------------------------------------
    def check_external_routes(self):
        """Determine which external routes are redistributed and visible.

        External routes do not propagate into stub/totally_stub areas.
        """
        external = {}

        for ext in self.topology.get('external_routes', []):
            prefix = ext['prefix']
            origin = ext['origin']
            expected_action = ext.get('expected_action', 'permit')
            cfg = self.configs[origin]

            permitted = False
            for rd in cfg['redistribute']:
                if rd['protocol'] == 'static':
                    has_static = any(
                        ipaddress.ip_network(s['prefix'], strict=False)
                        == ipaddress.ip_network(prefix, strict=False)
                        for s in cfg['static_routes']
                    )
                    if not has_static:
                        continue
                    if 'route_map' in rd:
                        permitted = route_map_permits(
                            cfg['route_maps'], cfg['prefix_lists'],
                            rd['route_map'], prefix)
                    else:
                        permitted = True

            visible_on = []
            if permitted:
                visited = set()
                queue = [origin]
                while queue:
                    cur = queue.pop(0)
                    if cur in visited:
                        continue
                    visited.add(cur)
                    visible_on.append(cur)
                    for link in self.topology['links']:
                        key = (f"{link['endpoints'][0]}-"
                               f"{link['endpoints'][1]}")
                        adj = self.adjacencies.get(key, {})
                        if adj.get('status') != 'FULL':
                            continue
                        if cur not in link['endpoints']:
                            continue
                        nbr = [e for e in link['endpoints'] if e != cur][0]
                        if nbr in visited:
                            continue
                        nbr_cfg = self.configs[nbr]
                        area_id = adj['area']
                        nbr_area_type = get_area_type(nbr_cfg, area_id)
                        if nbr_area_type in ('stub', 'totally_stub'):
                            continue
                        queue.append(nbr)

            external[prefix] = {
                'origin': origin,
                'permitted': permitted,
                'expected_action': expected_action,
                'visible_on': sorted(visible_on)
            }

        return external

    # ------------------------------------------------------------------
    def validate(self):
        """Run full validation and return structured report."""
        adj = self.validate_adjacencies()
        area_types = self.check_area_types()
        summarization = self.check_summarization()
        costs = self.check_costs()
        reach = self.compute_reachability()
        ext = self.check_external_routes()

        return {
            'adjacencies': adj,
            'area_types': area_types,
            'summarization': summarization,
            'costs': costs,
            'loopback_reachability': reach,
            'external_routes': ext,
        }

    # ------------------------------------------------------------------
    def print_report(self, report):
        """Print human-readable validation report."""
        print("=" * 62)
        print("  OSPF Configuration Design Validation Report")
        print("=" * 62)

        all_adj = True
        print("\n--- Link Adjacencies ---")
        for link, st in report['adjacencies'].items():
            tag = "FULL" if st['status'] == 'FULL' else "DOWN"
            if tag == "DOWN":
                all_adj = False
            line = f"  {link}: {tag}"
            if 'reason' in st:
                line += f"  -- {st['reason']}"
            elif 'area' in st:
                line += (f"  [area {st['area']}, "
                         f"{st.get('area_type', 'normal')}]")
            print(line)

        all_types = True
        print("\n--- Area Types ---")
        for area, info in report['area_types'].items():
            for router, rinfo in info['routers'].items():
                ok = "OK" if rinfo['correct'] else "WRONG"
                if not rinfo['correct']:
                    all_types = False
                print(f"  Area {area} on {router}: "
                      f"{rinfo['configured']} "
                      f"(expected {info['expected']}) [{ok}]")

        all_summ = True
        print("\n--- Route Summarization ---")
        for key, info in report['summarization'].items():
            ok = "OK" if info['present'] else "MISSING"
            if not info['present']:
                all_summ = False
            print(f"  {key}: {ok}")

        all_costs = True
        print("\n--- OSPF Costs ---")
        for key, info in report['costs'].items():
            ok = "OK" if info['correct'] else "WRONG"
            if not info['correct']:
                all_costs = False
            print(f"  {key}: expected={info['expected']} "
                  f"actual={info['actual']} [{ok}]")

        all_reach = True
        print("\n--- Loopback Reachability ---")
        for path, ok_flag in report['loopback_reachability'].items():
            if not ok_flag:
                all_reach = False
            print(f"  {path}: "
                  f"{'reachable' if ok_flag else 'UNREACHABLE'}")

        all_ext = True
        print("\n--- External Route Redistribution ---")
        for pfx, info in report['external_routes'].items():
            if info['expected_action'] == 'deny':
                if info['permitted']:
                    print(f"  {pfx}: SHOULD BE DENIED but is permitted")
                    all_ext = False
                else:
                    print(f"  {pfx}: correctly denied")
            else:
                if not info['permitted']:
                    print(f"  {pfx}: BLOCKED by filter on "
                          f"{info['origin']}")
                    all_ext = False
                else:
                    all_rtrs = sorted(self.configs.keys())
                    vis = info['visible_on']
                    print(f"  {pfx}: permitted, visible on {vis}")

        overall = (all_adj and all_types and all_summ
                   and all_costs and all_reach and all_ext)
        print("\n--- Summary ---")
        print(f"  Adjacencies:       "
              f"{'PASS' if all_adj else 'FAIL'}")
        print(f"  Area Types:        "
              f"{'PASS' if all_types else 'FAIL'}")
        print(f"  Summarization:     "
              f"{'PASS' if all_summ else 'FAIL'}")
        print(f"  OSPF Costs:        "
              f"{'PASS' if all_costs else 'FAIL'}")
        print(f"  Reachability:      "
              f"{'PASS' if all_reach else 'FAIL'}")
        print(f"  External routes:   "
              f"{'PASS' if all_ext else 'FAIL'}")
        print(f"  Overall:           "
              f"{'PASS' if overall else 'FAIL'}")
        return overall


if __name__ == '__main__':
    v = OSPFValidator('/app/configs')
    report = v.validate()
    ok = v.print_report(report)
    if '--json' in sys.argv:
        print("\n--- JSON ---")
        print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if ok else 1)
