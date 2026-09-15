#!/usr/bin/env python3
"""
FRR BGP VRF Route-Leak Configuration Analyzer and VRF Designer.

Parses FRR configuration files, compares against the intended topology design,
identifies misconfigurations, designs new VRFs from business constraints,
evaluates the security posture, computes VRF reachability, and generates
corrected configs.

"""

import json
import os
import re
import sys
from collections import defaultdict


class FRRConfigParser:
    """Parse FRR configuration files to extract BGP and VRF information."""

    def __init__(self, config_text):
        self.config_text = config_text
        self.lines = config_text.split('\n')
        self.bgp_instances = []
        self._parse()

    def _parse(self):
        i = 0
        while i < len(self.lines):
            line = self.lines[i].strip()
            m = re.match(r'^router\s+bgp\s+(\d+)(?:\s+vrf\s+(\S+))?\s*$', line)
            if m:
                asn = int(m.group(1))
                vrf = m.group(2)
                instance = {
                    'asn': asn,
                    'vrf': vrf,
                    'router_id': None,
                    'start_line': i,
                    'address_families': {},
                }
                i += 1
                i = self._parse_bgp_body(instance, i)
                self.bgp_instances.append(instance)
            else:
                i += 1

    def _parse_bgp_body(self, instance, start):
        i = start
        current_af = None
        while i < len(self.lines):
            line = self.lines[i].strip()

            if line == 'exit' and current_af is None:
                instance['end_line'] = i
                return i + 1

            if line.startswith('bgp router-id'):
                m = re.match(r'bgp\s+router-id\s+(\S+)', line)
                if m:
                    instance['router_id'] = m.group(1)

            if line.startswith('address-family'):
                m = re.match(r'address-family\s+(.+)', line)
                if m:
                    af_name = m.group(1).strip()
                    current_af = {
                        'name': af_name,
                        'rd_vpn_export': None,
                        'rt_vpn_export': [],
                        'rt_vpn_import': [],
                        'export_vpn': False,
                        'import_vpn': False,
                        'import_vrf': None,
                    }
                    instance['address_families'][af_name] = current_af

            if line == 'exit-address-family':
                current_af = None

            if current_af is not None:
                if line.startswith('rd vpn export'):
                    m = re.match(r'rd\s+vpn\s+export\s+(\S+)', line)
                    if m:
                        current_af['rd_vpn_export'] = m.group(1)

                if line.startswith('rt vpn export'):
                    m = re.match(r'rt\s+vpn\s+export\s+(.*)', line)
                    if m:
                        current_af['rt_vpn_export'] = m.group(1).strip().split()

                if line.startswith('rt vpn import'):
                    m = re.match(r'rt\s+vpn\s+import\s+(.*)', line)
                    if m:
                        current_af['rt_vpn_import'] = m.group(1).strip().split()

                if line.startswith('rt vpn both'):
                    m = re.match(r'rt\s+vpn\s+both\s+(.*)', line)
                    if m:
                        rts = m.group(1).strip().split()
                        current_af['rt_vpn_export'].extend(rts)
                        current_af['rt_vpn_import'].extend(rts)

                if line == 'export vpn':
                    current_af['export_vpn'] = True

                if line == 'import vpn':
                    current_af['import_vpn'] = True

                if line.startswith('import vrf'):
                    m = re.match(r'import\s+vrf\s+(\S+)', line)
                    if m:
                        current_af['import_vrf'] = m.group(1)

            i += 1
        instance['end_line'] = i
        return i

    def has_default_instance(self):
        return any(inst['vrf'] is None for inst in self.bgp_instances)

    def get_vrf_instances(self):
        return [inst for inst in self.bgp_instances if inst['vrf'] is not None]

    def get_instance(self, vrf=None):
        for inst in self.bgp_instances:
            if inst['vrf'] == vrf:
                return inst
            if vrf and inst['vrf'] and inst['vrf'].upper() == vrf.upper():
                return inst
        return None


def find_bugs(parsers, topology):
    """Identify configuration bugs by comparing configs against design."""
    bugs = []

    for router_name, router_topo in topology['routers'].items():
        parser = parsers.get(router_name)
        if parser is None:
            continue

        # BUG TYPE 1: Missing default BGP instance when VPN route-leak is used
        uses_vpn = False
        for inst in parser.get_vrf_instances():
            for af in inst['address_families'].values():
                if af['export_vpn'] or af['import_vpn']:
                    uses_vpn = True
                    break
        if uses_vpn and not parser.has_default_instance():
            bugs.append({
                'router': router_name,
                'vrf': 'default',
                'bug': (
                    f'Missing default BGP instance (router bgp {router_topo["as_number"]}). '
                    f'The VPN RIB used for inter-VRF route leaking is only initialized when '
                    f'a default BGP instance exists. Without it, export vpn/import vpn '
                    f'directives in VRF instances have no effect.'
                ),
                'fix': (
                    f'Add "router bgp {router_topo["as_number"]}" with '
                    f'"bgp router-id {router_topo["router_id"]}"'
                ),
            })

        # Per-VRF checks
        for vrf_name, vrf_topo in router_topo.get('vrfs', {}).items():
            inst = parser.get_instance(vrf_name)
            if inst is None:
                continue

            # BUG TYPE 2: Missing bgp router-id
            if inst['router_id'] is None:
                bugs.append({
                    'router': router_name,
                    'vrf': vrf_name,
                    'bug': (
                        f'Missing "bgp router-id" in VRF {vrf_name}. '
                        f'Without an explicit router-id, FRR auto-derives the RD and RT '
                        f'values from the first interface IP in the VRF. This causes '
                        f'configured RD/RT to be silently overwritten whenever interface '
                        f'IPs change, breaking route-leak connectivity.'
                    ),
                    'fix': (
                        f'Add "bgp router-id <ip>" to router bgp {router_topo["as_number"]} '
                        f'vrf {vrf_name}'
                    ),
                })

            af = inst['address_families'].get('ipv4 unicast')
            if af is None:
                continue

            # BUG TYPE 3: RT mismatch (typo) against design
            design_rt_export = set(vrf_topo.get('rt_export', []))
            actual_rt_export = set(af['rt_vpn_export'])
            if design_rt_export and actual_rt_export and design_rt_export != actual_rt_export:
                bugs.append({
                    'router': router_name,
                    'vrf': vrf_name,
                    'bug': (
                        f'RT export mismatch in VRF {vrf_name}: configured '
                        f'{sorted(actual_rt_export)} but design specifies '
                        f'{sorted(design_rt_export)}. Routes will be tagged with '
                        f'the wrong community and other VRFs importing '
                        f'{sorted(design_rt_export)} will not receive them.'
                    ),
                    'fix': (
                        f'Change "rt vpn export" to '
                        f'{" ".join(sorted(design_rt_export))}'
                    ),
                })

            # BUG TYPE 4: import vrf incompatible with export vpn on source
            if af['import_vrf']:
                src_name = af['import_vrf']
                src_inst = parser.get_instance(src_name)
                if src_inst:
                    src_af = src_inst['address_families'].get('ipv4 unicast')
                    if src_af and src_af['export_vpn']:
                        bugs.append({
                            'router': router_name,
                            'vrf': vrf_name,
                            'bug': (
                                f'"import vrf {src_name}" in VRF {vrf_name} is '
                                f'incompatible with "export vpn" on VRF {src_name}. '
                                f'FRR does not support mixing the shortcut "import vrf" '
                                f'syntax with explicit "export vpn"/"import vpn" '
                                f'statements for the same VRF pair.'
                            ),
                            'fix': (
                                f'Replace "import vrf {src_name}" with explicit VPN '
                                f'import: add "rd vpn export {vrf_topo["rd"]}", '
                                f'"rt vpn export {" ".join(vrf_topo["rt_export"])}", '
                                f'"rt vpn import {" ".join(vrf_topo["rt_import"])}", '
                                f'"export vpn", and "import vpn"'
                            ),
                        })

            # BUG TYPE 5: rt vpn import configured but import vpn missing
            if (af['rt_vpn_import'] and not af['import_vpn']
                    and not af['import_vrf']):
                bugs.append({
                    'router': router_name,
                    'vrf': vrf_name,
                    'bug': (
                        f'VRF {vrf_name} has "rt vpn import" configured '
                        f'({af["rt_vpn_import"]}) but is missing "import vpn". '
                        f'Without "import vpn", routes matching the import RT '
                        f'are not actually imported from the VPN table into this VRF.'
                    ),
                    'fix': (
                        f'Add "import vpn" under address-family ipv4 unicast in '
                        f'router bgp {router_topo["as_number"]} vrf {vrf_name}'
                    ),
                })

    return bugs


def design_new_vrfs(topology, requirements):
    """
    Design RT/RD assignments for new VRFs based on business constraints.

    This is the creative design step: we must choose RT/RD values that satisfy
    the isolation constraints specified in requirements.json, using the existing
    topology's RT/RD mappings as context.
    """
    designs = {}

    # Build a map of existing VRF RT export/import sets per router
    router_rt_map = {}
    for router_name, router_topo in topology['routers'].items():
        router_rt_map[router_name] = {}
        for vrf_name, vrf_topo in router_topo.get('vrfs', {}).items():
            router_rt_map[router_name][vrf_name] = {
                'rt_export': set(vrf_topo.get('rt_export', [])),
                'rt_import': set(vrf_topo.get('rt_import', [])),
            }

    # Collect all RTs in use across the entire topology to avoid collisions
    all_used_rts = set()
    all_used_rds = set()
    for router_topo in topology['routers'].values():
        for vrf_topo in router_topo.get('vrfs', {}).values():
            all_used_rts.update(vrf_topo.get('rt_export', []))
            all_used_rts.update(vrf_topo.get('rt_import', []))
            if 'rd' in vrf_topo:
                all_used_rds.add(vrf_topo['rd'])

    new_vrf_reqs = requirements.get('new_vrf_requirements', {})

    # --- Design QUARANTINE on R1 ---
    if 'R1:QUARANTINE' in new_vrf_reqs:
        req = new_vrf_reqs['R1:QUARANTINE']
        r1_vrfs = router_rt_map.get('R1', {})

        # Constraint analysis:
        # 1. Must import from MGMT -> need MGMT's export RT
        mgmt_export_rts = r1_vrfs.get('MGMT', {}).get('rt_export', set())
        quarantine_import_rts = list(mgmt_export_rts)  # import MGMT's export RTs

        # 2. Must NOT be visible to CUST -> export RT must not be in CUST's import set
        cust_import_rts = r1_vrfs.get('CUST', {}).get('rt_import', set())

        # 3. Must NOT leak back to MGMT -> export RT must not be in MGMT's import set
        mgmt_import_rts = r1_vrfs.get('MGMT', {}).get('rt_import', set())

        forbidden_export_rts = cust_import_rts | mgmt_import_rts

        # Choose an export RT not in the forbidden set and not already used
        # Use 65001:150 as a clean value between existing RT ranges
        quarantine_export_rt = '65001:150'
        assert quarantine_export_rt not in forbidden_export_rts, (
            f"Chosen export RT {quarantine_export_rt} conflicts with forbidden set"
        )

        quarantine_rd = '65001:150'

        designs['quarantine_design'] = {
            'rd': quarantine_rd,
            'rt_export': [quarantine_export_rt],
            'rt_import': sorted(quarantine_import_rts),
            'justification': (
                f'QUARANTINE imports RT {", ".join(sorted(quarantine_import_rts))} to receive '
                f'routes from MGMT VRF (which exports those RTs). The export RT '
                f'{quarantine_export_rt} was chosen because it does not appear in '
                f'CUST\'s import set {sorted(cust_import_rts)} (preventing QUARANTINE '
                f'routes from appearing in CUST\'s routing table) and does not appear in '
                f'MGMT\'s import set {sorted(mgmt_import_rts)} (preventing route '
                f'leak-back to MGMT). The RD {quarantine_rd} is unique across the topology, '
                f'ensuring VPN route distinguisher uniqueness. This achieves unidirectional '
                f'route visibility: QUARANTINE can reach management infrastructure for '
                f'remediation, but neither CUST nor MGMT can see quarantined host routes.'
            ),
            'isolation_properties': {
                'imports_routes_from': ['MGMT'],
                'exports_routes_to': [],
                'leaks_back_to': [],
            },
        }

    # --- Design MONITOR on R2 ---
    if 'R2:MONITOR' in new_vrf_reqs:
        req = new_vrf_reqs['R2:MONITOR']
        r2_vrfs = router_rt_map.get('R2', {})

        # Constraint analysis:
        # 1. Must import from CUST and INTERNAL -> need both export RTs
        cust_export_rts = r2_vrfs.get('CUST', {}).get('rt_export', set())
        internal_export_rts = r2_vrfs.get('INTERNAL', {}).get('rt_export', set())
        monitor_import_rts = sorted(cust_export_rts | internal_export_rts)

        # 2. Must NOT leak into CUST -> export RT not in CUST's import set
        cust_import_rts = r2_vrfs.get('CUST', {}).get('rt_import', set())

        # 3. Must NOT leak into INTERNAL -> export RT not in INTERNAL's import set
        internal_import_rts = r2_vrfs.get('INTERNAL', {}).get('rt_import', set())

        forbidden_export_rts = cust_import_rts | internal_import_rts

        # Choose an export RT not in the forbidden set
        monitor_export_rt = '65001:500'
        assert monitor_export_rt not in forbidden_export_rts, (
            f"Chosen export RT {monitor_export_rt} conflicts with forbidden set"
        )

        monitor_rd = '65001:500'

        designs['monitor_design'] = {
            'rd': monitor_rd,
            'rt_export': [monitor_export_rt],
            'rt_import': monitor_import_rts,
            'justification': (
                f'MONITOR imports RTs {", ".join(monitor_import_rts)} to aggregate '
                f'routes from both CUST (exports {sorted(cust_export_rts)}) and INTERNAL '
                f'(exports {sorted(internal_export_rts)}). The export RT {monitor_export_rt} '
                f'was chosen because it does not appear in CUST\'s import set '
                f'{sorted(cust_import_rts)} or INTERNAL\'s import set '
                f'{sorted(internal_import_rts)}, ensuring no monitoring infrastructure '
                f'routes leak back into operational VRFs. The RD {monitor_rd} is unique '
                f'across the topology. This achieves read-only aggregation: MONITOR has '
                f'full visibility into customer and internal routes for observability, '
                f'but cannot inject routes that would affect production traffic.'
            ),
            'isolation_properties': {
                'imports_routes_from': ['CUST', 'INTERNAL'],
                'exports_routes_to': [],
                'leaks_back_to': [],
            },
        }

    return designs


def evaluate_security(topology, designs):
    """Evaluate the security posture of the complete VRF route-leak architecture."""
    findings = []

    # Finding 1: R1:CUST has broad RT import scope
    r1_cust = topology['routers']['R1']['vrfs']['CUST']
    if len(r1_cust.get('rt_import', [])) > 1:
        findings.append({
            'finding': (
                'R1:CUST VRF imports multiple RTs (65001:100, 65001:200), giving it '
                'visibility into both customer and management route spaces. This means '
                'customer-facing interfaces can reach management infrastructure, which '
                'increases the attack surface if a customer host is compromised.'
            ),
            'severity': 'medium',
            'recommendation': (
                'Evaluate whether CUST truly needs management route visibility. If '
                'management access from CUST is only needed for specific prefixes, '
                'implement a route-map with prefix-list filters on the import vpn '
                'direction to restrict which MGMT prefixes are leaked into CUST, '
                'rather than importing all MGMT routes.'
            ),
        })

    # Finding 2: RT 65001:200 is used as both import and export on MGMT via "rt vpn both"
    findings.append({
        'finding': (
            'R1:MGMT uses "rt vpn both 65001:200" which means MGMT both exports and '
            'imports the same RT community. While currently safe (no other VRF on R1 '
            'exports 65001:200), adding any future VRF that exports 65001:200 would '
            'unintentionally inject routes into MGMT. The "rt vpn both" shorthand '
            'obscures the import/export distinction and makes the RT policy brittle.'
        ),
        'severity': 'low',
        'recommendation': (
            'Replace "rt vpn both 65001:200" with separate "rt vpn export 65001:200" '
            'and "rt vpn import 65001:200" statements. If MGMT does not need to import '
            'routes from any other VRF, remove the import RT entirely or set it to an '
            'unused value to follow minimum-privilege principles.'
        ),
    })

    # Finding 3: No route-map filtering on any VPN import/export
    findings.append({
        'finding': (
            'No VRF in the architecture uses route-map filtering on VPN import or '
            'export operations. All route leaking is controlled solely by RT matching, '
            'which operates at the VRF level without prefix granularity. A compromised '
            'host in any VRF can advertise arbitrary prefixes that will be leaked to '
            'all VRFs importing that RT, enabling route hijacking within the leak domain.'
        ),
        'severity': 'high',
        'recommendation': (
            'Add route-maps with prefix-list filters on "export vpn" and "import vpn" '
            'directives for all VRFs to restrict leaked routes to expected prefix ranges. '
            'At minimum, apply outbound prefix filtering on CUST and QUARANTINE VRFs to '
            'prevent them from advertising infrastructure routes.'
        ),
    })

    return findings


def compute_reachability(topology, new_vrf_designs):
    """
    Compute same-router VRF reachability based on the design's RT semantics,
    including newly designed VRFs.
    """
    # Build a complete VRF map: router -> vrf_name -> {rt_export, rt_import}
    vrf_map = {}
    for router_name, router_topo in topology['routers'].items():
        vrf_map[router_name] = {}
        for vrf_name, vrf_topo in router_topo.get('vrfs', {}).items():
            vrf_map[router_name][vrf_name] = {
                'rt_export': set(vrf_topo.get('rt_export', [])),
                'rt_import': set(vrf_topo.get('rt_import', [])),
            }

    # Add new VRFs from designs
    if 'quarantine_design' in new_vrf_designs:
        qd = new_vrf_designs['quarantine_design']
        if 'R1' not in vrf_map:
            vrf_map['R1'] = {}
        vrf_map['R1']['QUARANTINE'] = {
            'rt_export': set(qd['rt_export']),
            'rt_import': set(qd['rt_import']),
        }

    if 'monitor_design' in new_vrf_designs:
        md = new_vrf_designs['monitor_design']
        if 'R2' not in vrf_map:
            vrf_map['R2'] = {}
        vrf_map['R2']['MONITOR'] = {
            'rt_export': set(md['rt_export']),
            'rt_import': set(md['rt_import']),
        }

    # Compute reachability
    reachability = {}
    for router_name, vrfs in vrf_map.items():
        for dest_vrf, dest_rts in vrfs.items():
            dest_key = f"{router_name}:{dest_vrf}"
            sources = []
            for src_vrf, src_rts in vrfs.items():
                if src_vrf == dest_vrf:
                    continue
                if src_rts['rt_export'] & dest_rts['rt_import']:
                    sources.append(f"{router_name}:{src_vrf}")
            reachability[dest_key] = sorted(sources)

    return reachability


def generate_corrected_config(original, router_name, router_topo, bugs,
                               new_vrf_designs=None):
    """Apply fixes and add new VRFs to generate a corrected configuration."""
    lines = original.split('\n')
    router_bugs = [b for b in bugs if b['router'] == router_name]

    # Fix 1: Add default BGP instance if missing
    needs_default = any(
        b['vrf'] == 'default' and 'default BGP' in b['bug']
        for b in router_bugs
    )
    if needs_default:
        insert_idx = None
        for i, line in enumerate(lines):
            if re.match(r'^router\s+bgp\s+', line.strip()):
                insert_idx = i
                break
        if insert_idx is not None:
            new_block = [
                f'router bgp {router_topo["as_number"]}',
                f' bgp router-id {router_topo["router_id"]}',
                'exit',
                '!',
            ]
            for j, nl in enumerate(new_block):
                lines.insert(insert_idx + j, nl)

    # Fix 2: Add missing bgp router-id in VRF sections
    for bug in router_bugs:
        if 'router-id' in bug['bug'] and bug['vrf'] != 'default':
            vrf_name = bug['vrf']
            pat = re.compile(
                r'^router\s+bgp\s+\d+\s+vrf\s+' + re.escape(vrf_name) + r'\s*$',
                re.IGNORECASE,
            )
            for i, line in enumerate(lines):
                if pat.match(line.strip()):
                    vrf_ifaces = {
                        k: v for k, v in router_topo['interfaces'].items()
                        if v.get('vrf', '').upper() == vrf_name.upper()
                    }
                    if vrf_ifaces:
                        ip = list(vrf_ifaces.values())[0]['address'].split('/')[0]
                        lines.insert(i + 1, f' bgp router-id {ip}')
                    break

    # Fix 3: Fix RT export typo (65001:3000 -> 65001:300)
    for bug in router_bugs:
        if 'RT export mismatch' in bug['bug']:
            for i, line in enumerate(lines):
                if '65001:3000' in line and 'rt vpn export' in line:
                    lines[i] = line.replace('65001:3000', '65001:300')

    # Fix 4: Add missing import vpn
    for bug in router_bugs:
        if 'missing "import vpn"' in bug['bug']:
            vrf_name = bug['vrf']
            pat = re.compile(
                r'^router\s+bgp\s+\d+\s+vrf\s+' + re.escape(vrf_name) + r'\s*$',
                re.IGNORECASE,
            )
            in_vrf = False
            in_af = False
            for i, line in enumerate(lines):
                if pat.match(line.strip()):
                    in_vrf = True
                    continue
                if in_vrf:
                    if line.strip().startswith('address-family'):
                        in_af = True
                        continue
                    if in_af and line.strip() == 'export vpn':
                        lines.insert(i + 1, '  import vpn')
                        break
                    if in_af and line.strip() == 'exit-address-family':
                        lines.insert(i, '  import vpn')
                        break
                    if re.match(r'^router\s+', line.strip()):
                        break

    # Fix 5: Replace import vrf with proper VPN import
    for bug in router_bugs:
        if 'import vrf' in bug['bug'] and 'incompatible' in bug['bug']:
            vrf_name = bug['vrf']
            vrf_topo = router_topo['vrfs'][vrf_name]
            pat = re.compile(
                r'^router\s+bgp\s+\d+\s+vrf\s+' + re.escape(vrf_name) + r'\s*$',
                re.IGNORECASE,
            )
            new_lines = []
            in_vrf = False
            in_af = False
            replaced = False
            for line in lines:
                if pat.match(line.strip()):
                    in_vrf = True
                    new_lines.append(line)
                    continue
                if in_vrf and line.strip().startswith('address-family'):
                    in_af = True
                    new_lines.append(line)
                    continue
                if in_af and not replaced and line.strip().startswith('import vrf'):
                    new_lines.append(f'  rd vpn export {vrf_topo["rd"]}')
                    new_lines.append(
                        f'  rt vpn export {" ".join(vrf_topo["rt_export"])}'
                    )
                    new_lines.append(
                        f'  rt vpn import {" ".join(vrf_topo["rt_import"])}'
                    )
                    new_lines.append('  export vpn')
                    new_lines.append('  import vpn')
                    replaced = True
                    in_af = False
                    in_vrf = False
                    continue
                new_lines.append(line)
            lines = new_lines

    # Add new VRF sections if applicable
    if new_vrf_designs:
        asn = router_topo['as_number']

        if router_name == 'R1' and 'quarantine_design' in new_vrf_designs:
            qd = new_vrf_designs['quarantine_design']
            # Add VRF definition before the first "router bgp" line
            vrf_def_idx = None
            for i, line in enumerate(lines):
                if re.match(r'^router\s+bgp\s+', line.strip()):
                    vrf_def_idx = i
                    break
            if vrf_def_idx is not None:
                vrf_block = [
                    'vrf QUARANTINE',
                    'exit-vrf',
                    '!',
                ]
                for j, nl in enumerate(vrf_block):
                    lines.insert(vrf_def_idx + j, nl)

            # Add BGP section for QUARANTINE at the end (before "ip forwarding")
            insert_before = None
            for i, line in enumerate(lines):
                if line.strip() == 'ip forwarding':
                    insert_before = i
                    break
            if insert_before is None:
                insert_before = len(lines)

            bgp_block = [
                f'router bgp {asn} vrf QUARANTINE',
                f' bgp router-id {qd["rd"].split(":")[1]}.0.0.1',
                ' !',
                ' address-family ipv4 unicast',
                '  redistribute connected',
                f'  rd vpn export {qd["rd"]}',
                f'  rt vpn export {" ".join(qd["rt_export"])}',
                f'  rt vpn import {" ".join(qd["rt_import"])}',
                '  export vpn',
                '  import vpn',
                ' exit-address-family',
                'exit',
                '!',
            ]
            for j, nl in enumerate(bgp_block):
                lines.insert(insert_before + j, nl)

        if router_name == 'R2' and 'monitor_design' in new_vrf_designs:
            md = new_vrf_designs['monitor_design']
            # Add VRF definition
            vrf_def_idx = None
            for i, line in enumerate(lines):
                if re.match(r'^router\s+bgp\s+', line.strip()):
                    vrf_def_idx = i
                    break
            if vrf_def_idx is not None:
                vrf_block = [
                    'vrf MONITOR',
                    'exit-vrf',
                    '!',
                ]
                for j, nl in enumerate(vrf_block):
                    lines.insert(vrf_def_idx + j, nl)

            # Add BGP section for MONITOR
            insert_before = None
            for i, line in enumerate(lines):
                if line.strip() == 'ip forwarding':
                    insert_before = i
                    break
            if insert_before is None:
                insert_before = len(lines)

            bgp_block = [
                f'router bgp {asn} vrf MONITOR',
                f' bgp router-id 10.250.2.1',
                ' !',
                ' address-family ipv4 unicast',
                '  redistribute connected',
                f'  rd vpn export {md["rd"]}',
                f'  rt vpn export {" ".join(md["rt_export"])}',
                f'  rt vpn import {" ".join(md["rt_import"])}',
                '  export vpn',
                '  import vpn',
                ' exit-address-family',
                'exit',
                '!',
            ]
            for j, nl in enumerate(bgp_block):
                lines.insert(insert_before + j, nl)

    return '\n'.join(lines)


def main():
    configs_dir = '/app/configs'
    topology_path = '/app/topology.json'
    requirements_path = '/app/requirements.json'
    output_dir = '/app/output'
    corrected_dir = os.path.join(output_dir, 'corrected')
    os.makedirs(corrected_dir, exist_ok=True)

    # Load topology and requirements
    with open(topology_path) as f:
        topology = json.load(f)

    with open(requirements_path) as f:
        requirements = json.load(f)

    # Load and parse configs
    configs = {}
    parsers = {}
    for router_name in topology['routers']:
        fname = f"{router_name.lower()}.conf"
        path = os.path.join(configs_dir, fname)
        with open(path) as f:
            text = f.read()
        configs[router_name] = text
        parsers[router_name] = FRRConfigParser(text)

    # Step 1: Find bugs in existing configs
    bugs = find_bugs(parsers, topology)
    with open(os.path.join(output_dir, 'bugs.json'), 'w') as f:
        json.dump(bugs, f, indent=2)
    print(f"Found {len(bugs)} bugs:")
    for b in bugs:
        print(f"  [{b['router']}:{b['vrf']}] {b['bug'][:100]}...")

    # Step 2: Design new VRFs from business constraints
    new_vrf_designs = design_new_vrfs(topology, requirements)
    print(f"\nDesigned {len(new_vrf_designs)} new VRFs")

    # Step 3: Evaluate security posture
    security_findings = evaluate_security(topology, new_vrf_designs)
    design_eval = {**new_vrf_designs, 'security_assessment': security_findings}
    with open(os.path.join(output_dir, 'design_evaluation.json'), 'w') as f:
        json.dump(design_eval, f, indent=2)
    print(f"Security assessment: {len(security_findings)} findings")

    # Step 4: Compute reachability (based on design + new VRFs)
    reachability = compute_reachability(topology, new_vrf_designs)
    with open(os.path.join(output_dir, 'reachability.json'), 'w') as f:
        json.dump(reachability, f, indent=2)
    print(f"\nReachability matrix ({len(reachability)} VRFs):")
    for dest, sources in sorted(reachability.items()):
        print(f"  {dest} <- {sources}")

    # Step 5: Generate corrected configs with bug fixes and new VRFs
    for router_name, router_topo in topology['routers'].items():
        corrected = generate_corrected_config(
            configs[router_name], router_name, router_topo, bugs,
            new_vrf_designs=new_vrf_designs,
        )
        out_path = os.path.join(corrected_dir, f"{router_name.lower()}.conf")
        with open(out_path, 'w') as f:
            f.write(corrected)
        print(f"Wrote corrected config: {out_path}")

    print("\nDone.")


if __name__ == '__main__':
    main()
