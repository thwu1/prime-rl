
import json
import os
import re
import subprocess
import pytest


def load_report():
    with open('/app/analysis_report.json') as f:
        return json.load(f)


def load_commands():
    with open('/app/optimized_tc_commands.sh') as f:
        return f.read()


def rate_str_to_mbit(rate_str):
    """Convert rate string like '3gbit' or '1600mbit' to float mbit."""
    rate_str = str(rate_str).lower().strip()
    if rate_str.endswith('gbit'):
        return float(rate_str.replace('gbit', '')) * 1000
    elif rate_str.endswith('mbit'):
        return float(rate_str.replace('mbit', ''))
    return float(rate_str)


class TestTCGenerator:
    """Tests for the fixed tc_generator.py (Part 1)."""

    @classmethod
    def setup_class(cls):
        """Run the fixed generator to verify it works."""
        result = subprocess.run(
            ['python3', '/app/tc_generator.py'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, f"Generator failed: {result.stderr}"

    def test_generator_output_files_exist(self):
        assert os.path.exists('/app/tc_commands.sh')
        assert os.path.exists('/app/tc_report.json')

    def test_dscp_to_tos_encoding(self):
        """DSCP values must be correctly encoded as TOS bytes in tc commands."""
        with open('/app/tc_commands.sh') as f:
            commands = f.read()
        # DSCP 46 -> TOS 0xb8
        assert '0xb8' in commands, "DSCP 46 should map to TOS 0xb8"
        # DSCP 44 -> TOS 0xb0
        assert '0xb0' in commands, "DSCP 44 should map to TOS 0xb0"
        # DSCP 26 -> TOS 0x68
        assert '0x68' in commands, "DSCP 26 should map to TOS 0x68"

    def test_class_parent_hierarchy(self):
        """Child class tc commands must reference parent class, not root."""
        with open('/app/tc_commands.sh') as f:
            commands = f.read()
        class_lines = [l for l in commands.split('\n') if 'class add' in l]
        for line in class_lines:
            if 'classid 1:11' in line or 'classid 1:12' in line:
                assert 'parent 1:10' in line, \
                    f"Expected parent 1:10: {line}"
            if 'classid 1:21' in line or 'classid 1:22' in line:
                assert 'parent 1:20' in line, \
                    f"Expected parent 1:20: {line}"
            if 'classid 1:31' in line or 'classid 1:32' in line:
                assert 'parent 1:30' in line, \
                    f"Expected parent 1:30: {line}"

    def test_ecn_safe_filter_mask(self):
        """All u32 TOS filters must use 0xfc mask to exclude ECN bits."""
        with open('/app/tc_commands.sh') as f:
            commands = f.read()
        filter_lines = [l for l in commands.split('\n')
                        if 'filter' in l and 'u32' in l and 'tos' in l]
        assert len(filter_lines) >= 6, \
            f"Expected >= 6 filters, got {len(filter_lines)}"
        for line in filter_lines:
            assert '0xfc' in line, f"Filter missing 0xfc mask: {line}"

    def test_dscp_zero_has_filter(self):
        """DSCP 0 (Best Effort) must have a filter despite being falsy."""
        with open('/app/tc_commands.sh') as f:
            commands = f.read()
        filter_lines = [l for l in commands.split('\n')
                        if 'filter' in l and 'u32' in l]
        has_dscp0 = any('0x00' in l and '0xfc' in l for l in filter_lines)
        assert has_dscp0, "Missing filter for DSCP 0 (control_default class)"

    def test_report_includes_dscp_zero(self):
        """tc_report.json must include a filter entry for DSCP 0."""
        with open('/app/tc_report.json') as f:
            report = json.load(f)
        dscp_values = [f['dscp'] for f in report['filters']]
        assert 0 in dscp_values, "Missing DSCP 0 filter in report"

    def test_report_filter_count(self):
        """Fixed generator must produce filters for all 6 leaf classes."""
        with open('/app/tc_report.json') as f:
            report = json.load(f)
        assert len(report['filters']) == 6, \
            f"Expected 6 filters, got {len(report['filters'])}"

    def test_report_tos_hex_values(self):
        """TOS hex values in report must reflect correct DSCP encoding."""
        with open('/app/tc_report.json') as f:
            report = json.load(f)
        tos_map = {f['dscp']: f['tos_hex'] for f in report['filters']}
        assert tos_map.get(46) == '0xb8', \
            f"DSCP 46 TOS should be 0xb8, got {tos_map.get(46)}"
        assert tos_map.get(0) == '0x00', \
            f"DSCP 0 TOS should be 0x00, got {tos_map.get(0)}"


class TestAnalyzerExecution:

    @classmethod
    def setup_class(cls):
        """Run the analyzer once before all tests."""
        result = subprocess.run(
            ['python3', '/app/tc_analyzer.py'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, f"Analyzer failed: {result.stderr}"

    def test_output_files_exist(self):
        assert os.path.exists('/app/analysis_report.json')
        assert os.path.exists('/app/optimized_tc_commands.sh')
        assert os.path.exists('/app/validation_summary.txt')

    def test_report_top_level_structure(self):
        report = load_report()
        assert 'violations' in report
        assert 'optimized_config' in report
        assert 'bandwidth_simulation' in report
        assert 'sla_compliance' in report


class TestViolationDetection:

    def test_violation_count(self):
        report = load_report()
        assert len(report['violations']) == 5, \
            f"Expected 5 violations, got {len(report['violations'])}: " \
            f"{json.dumps(report['violations'], indent=2)}"

    def test_overcommitment_eth0_business(self):
        report = load_report()
        matching = [v for v in report['violations']
                    if v['type'] == 'overcommitted' and v['interface'] == 'eth0']
        assert len(matching) == 1, f"Expected 1 eth0 overcommitted, got {matching}"
        assert 'business' in matching[0]['class_name']

    def test_ceil_violation_eth0_scavenger(self):
        report = load_report()
        matching = [v for v in report['violations']
                    if v['type'] == 'ceil_exceeds_parent_ceil'
                    and v['interface'] == 'eth0']
        assert len(matching) == 1
        assert 'scavenger' in matching[0]['class_name']

    def test_rate_exceeds_ceil_eth1_rdma_bulk(self):
        report = load_report()
        matching = [v for v in report['violations']
                    if v['type'] == 'rate_exceeds_ceil' and v['interface'] == 'eth1']
        assert len(matching) == 1
        assert 'rdma_bulk' in matching[0]['class_name']

    def test_overcommitment_eth1_gpu_rdma(self):
        report = load_report()
        matching = [v for v in report['violations']
                    if v['type'] == 'overcommitted' and v['interface'] == 'eth1']
        assert len(matching) == 1
        assert 'gpu_rdma' in matching[0]['class_name']

    def test_invalid_default_eth1(self):
        report = load_report()
        matching = [v for v in report['violations']
                    if v['type'] == 'invalid_default' and v['interface'] == 'eth1']
        assert len(matching) == 1

    def test_each_violation_has_details(self):
        report = load_report()
        for v in report['violations']:
            assert 'details' in v and len(v['details']) > 0, \
                f"Violation missing details: {v}"


class TestOptimizedConfig:

    def test_has_both_interfaces(self):
        report = load_report()
        assert 'eth0' in report['optimized_config']
        assert 'eth1' in report['optimized_config']

    def test_no_rate_exceeds_ceil(self):
        """All classes must have rate <= ceil after optimization."""
        report = load_report()
        for iface, config in report['optimized_config'].items():
            for cls in config['classes']:
                rate = rate_str_to_mbit(cls['rate'])
                ceil = rate_str_to_mbit(cls['ceil'])
                assert rate <= ceil + 0.01, \
                    f"[{iface}] {cls['name']}: rate {rate} > ceil {ceil}"

    def test_no_ceil_exceeds_parent_ceil(self):
        """All child class ceils must not exceed parent ceil."""
        report = load_report()
        hierarchy = {
            'eth0': {'1:10': ['1:11', '1:12'],
                     '1:20': ['1:21', '1:22', '1:23'],
                     '1:30': ['1:31', '1:32']},
            'eth1': {'1:10': ['1:11', '1:12'],
                     '1:20': ['1:21', '1:22'],
                     '1:30': ['1:31', '1:32']},
        }
        for iface, config in report['optimized_config'].items():
            classes = {c['classid']: c for c in config['classes']}
            for parent_id, child_ids in hierarchy[iface].items():
                parent_ceil = rate_str_to_mbit(classes[parent_id]['ceil'])
                for child_id in child_ids:
                    child_ceil = rate_str_to_mbit(classes[child_id]['ceil'])
                    assert child_ceil <= parent_ceil + 0.01, \
                        f"[{iface}] {child_id} ceil {child_ceil} > " \
                        f"parent {parent_id} ceil {parent_ceil}"

    def test_no_overcommitment(self):
        """Children rate sum must not exceed parent rate."""
        report = load_report()
        hierarchy = {
            'eth0': {'1:10': ['1:11', '1:12'],
                     '1:20': ['1:21', '1:22', '1:23'],
                     '1:30': ['1:31', '1:32']},
            'eth1': {'1:10': ['1:11', '1:12'],
                     '1:20': ['1:21', '1:22'],
                     '1:30': ['1:31', '1:32']},
        }
        for iface, config in report['optimized_config'].items():
            classes = {c['classid']: c for c in config['classes']}
            for parent_id, child_ids in hierarchy[iface].items():
                parent_rate = rate_str_to_mbit(classes[parent_id]['rate'])
                children_sum = sum(
                    rate_str_to_mbit(classes[cid]['rate']) for cid in child_ids
                )
                assert children_sum <= parent_rate + 0.01, \
                    f"[{iface}] {parent_id}: children sum {children_sum} > " \
                    f"parent rate {parent_rate}"

    def test_valid_defaults(self):
        """Default minor must reference an existing leaf class."""
        report = load_report()
        for iface, config in report['optimized_config'].items():
            default_minor = config['default_minor']
            leaf_minors = [
                int(c['classid'].split(':')[1])
                for c in config['classes']
                if c.get('is_leaf', False)
            ]
            assert default_minor in leaf_minors, \
                f"[{iface}] default_minor {default_minor} not in {leaf_minors}"

    def test_eth0_business_children_scaled(self):
        """Business children rates must be proportionally scaled to fit parent."""
        report = load_report()
        classes = {c['classid']: c
                   for c in report['optimized_config']['eth0']['classes']}
        # Original: web 2g, email 1g, db 2g (sum 5g) -> scale 4/5
        assert rate_str_to_mbit(classes['1:21']['rate']) == \
            pytest.approx(1600, abs=1)
        assert rate_str_to_mbit(classes['1:22']['rate']) == \
            pytest.approx(800, abs=1)
        assert rate_str_to_mbit(classes['1:23']['rate']) == \
            pytest.approx(1600, abs=1)

    def test_eth0_scavenger_ceil_clamped(self):
        """Scavenger ceil must be clamped to parent best_effort ceil (6gbit)."""
        report = load_report()
        classes = {c['classid']: c
                   for c in report['optimized_config']['eth0']['classes']}
        assert rate_str_to_mbit(classes['1:32']['ceil']) == \
            pytest.approx(6000, abs=1)

    def test_eth1_rdma_bulk_ceil_fixed(self):
        """rdma_bulk ceil must be >= rate after fixing rate>ceil."""
        report = load_report()
        classes = {c['classid']: c
                   for c in report['optimized_config']['eth1']['classes']}
        rate = rate_str_to_mbit(classes['1:12']['rate'])
        ceil = rate_str_to_mbit(classes['1:12']['ceil'])
        assert ceil >= rate - 0.01

    def test_eth1_gpu_rdma_children_scaled(self):
        """gpu_rdma children must be proportionally scaled (factor 3/4)."""
        report = load_report()
        classes = {c['classid']: c
                   for c in report['optimized_config']['eth1']['classes']}
        # Original: rdma_critical 12g, rdma_bulk 8g (sum 20g) -> scale 15/20
        assert rate_str_to_mbit(classes['1:11']['rate']) == \
            pytest.approx(9000, abs=1)
        assert rate_str_to_mbit(classes['1:12']['rate']) == \
            pytest.approx(6000, abs=1)

    def test_eth1_default_fixed(self):
        """eth1 default_minor must now reference an existing leaf class."""
        report = load_report()
        default = report['optimized_config']['eth1']['default_minor']
        assert default == 32, f"Expected eth1 default_minor=32, got {default}"

    def test_unchanged_classes_preserved(self):
        """Classes without violations should retain original values."""
        report = load_report()
        eth0 = {c['classid']: c
                for c in report['optimized_config']['eth0']['classes']}
        # realtime parent unchanged
        assert rate_str_to_mbit(eth0['1:10']['rate']) == pytest.approx(3000, abs=1)
        assert rate_str_to_mbit(eth0['1:10']['ceil']) == pytest.approx(10000, abs=1)
        # voip unchanged
        assert rate_str_to_mbit(eth0['1:11']['rate']) == pytest.approx(1000, abs=1)
        assert rate_str_to_mbit(eth0['1:11']['ceil']) == pytest.approx(3000, abs=1)


class TestBandwidthSimulation:

    def test_eth0_allocations(self):
        """Verify steady-state bandwidth allocation for eth0."""
        report = load_report()
        sim = report['bandwidth_simulation']['eth0']
        expected = {
            'voip': 800,
            'video_conferencing': 2200,
            'web_interactive': 2000,
            'email': 500,
            'database_sync': 1500,
            'general': 2000,
            'scavenger': 1000,
        }
        for name, expected_mbit in expected.items():
            actual = sim[name]['allocated_mbit']
            assert abs(actual - expected_mbit) <= 1, \
                f"eth0 {name}: expected {expected_mbit}mbit, got {actual}mbit"

    def test_eth1_allocations(self):
        """Verify steady-state bandwidth allocation for eth1."""
        report = load_report()
        sim = report['bandwidth_simulation']['eth1']
        expected = {
            'rdma_latency_critical': 10700,
            'rdma_bulk': 6000,
            'storage_sync': 4000,
            'storage_async': 3000,
            'cluster_mgmt': 500,
            'monitoring': 800,
        }
        for name, expected_mbit in expected.items():
            actual = sim[name]['allocated_mbit']
            assert abs(actual - expected_mbit) <= 1, \
                f"eth1 {name}: expected {expected_mbit}mbit, got {actual}mbit"

    def test_no_allocation_exceeds_ceil(self):
        """No class may be allocated more than its ceil."""
        report = load_report()
        for iface in ['eth0', 'eth1']:
            classes = {c['name']: c
                       for c in report['optimized_config'][iface]['classes']}
            sim = report['bandwidth_simulation'][iface]
            for name, alloc in sim.items():
                if name in classes:
                    ceil = rate_str_to_mbit(classes[name]['ceil'])
                    assert alloc['allocated_mbit'] <= ceil + 1, \
                        f"[{iface}] {name}: allocated " \
                        f"{alloc['allocated_mbit']} > ceil {ceil}"

    def test_no_allocation_exceeds_demand(self):
        """No class may be allocated more than its demand."""
        report = load_report()
        for iface in ['eth0', 'eth1']:
            sim = report['bandwidth_simulation'][iface]
            for name, alloc in sim.items():
                assert alloc['allocated_mbit'] <= alloc['demand_mbit'] + 1, \
                    f"[{iface}] {name}: allocated " \
                    f"{alloc['allocated_mbit']} > demand {alloc['demand_mbit']}"

    def test_total_within_link_speed(self):
        """Total allocation must not exceed link speed."""
        report = load_report()
        eth0_total = sum(
            a['allocated_mbit']
            for a in report['bandwidth_simulation']['eth0'].values()
        )
        assert eth0_total <= 10001, \
            f"eth0 total {eth0_total} exceeds 10gbit"

        eth1_total = sum(
            a['allocated_mbit']
            for a in report['bandwidth_simulation']['eth1'].values()
        )
        assert eth1_total <= 25001, \
            f"eth1 total {eth1_total} exceeds 25gbit"

    def test_utilization_consistency(self):
        """Utilization must equal allocated/demand."""
        report = load_report()
        for iface in ['eth0', 'eth1']:
            sim = report['bandwidth_simulation'][iface]
            for name, alloc in sim.items():
                if alloc['demand_mbit'] > 0:
                    expected_util = alloc['allocated_mbit'] / alloc['demand_mbit']
                    assert abs(alloc['utilization'] - expected_util) < 0.01, \
                        f"[{iface}] {name}: utilization {alloc['utilization']} " \
                        f"!= {expected_util}"


class TestSLACompliance:

    def test_sla_structure(self):
        report = load_report()
        sla = report['sla_compliance']
        assert 'violations' in sla
        assert 'compliant_count' in sla
        assert 'total_count' in sla

    def test_sla_total_count(self):
        report = load_report()
        assert report['sla_compliance']['total_count'] == 13

    def test_sla_violation_count(self):
        report = load_report()
        assert len(report['sla_compliance']['violations']) == 5, \
            f"Expected 5 SLA violations, got " \
            f"{len(report['sla_compliance']['violations'])}"

    def test_sla_compliant_count(self):
        report = load_report()
        assert report['sla_compliance']['compliant_count'] == 8

    def test_specific_sla_violations(self):
        """Verify exact set of SLA-failing classes."""
        report = load_report()
        violated = {v['class_name']
                    for v in report['sla_compliance']['violations']}
        expected = {'video_conferencing', 'web_interactive',
                    'rdma_latency_critical', 'rdma_bulk', 'storage_sync'}
        assert violated == expected, \
            f"SLA violation set mismatch: {violated} != {expected}"

    def test_sla_violation_ratios(self):
        """Verify SLA violation entries contain ratio information."""
        report = load_report()
        for v in report['sla_compliance']['violations']:
            assert 'required_ratio' in v
            assert 'actual_ratio' in v
            assert v['actual_ratio'] < v['required_ratio'], \
                f"{v['class_name']}: actual {v['actual_ratio']} >= " \
                f"required {v['required_ratio']}"


class TestTCCommands:

    def test_commands_file_exists(self):
        assert os.path.exists('/app/optimized_tc_commands.sh')

    def test_commands_both_interfaces(self):
        commands = load_commands()
        assert 'eth0' in commands
        assert 'eth1' in commands

    def test_dscp_to_tos_conversion(self):
        """Verify DSCP values are shifted left by 2 to get TOS."""
        commands = load_commands()
        # DSCP 46 (EF) -> TOS 0xb8
        assert '0xb8' in commands, "Missing TOS 0xb8 for DSCP 46"
        # DSCP 0 (BE) -> TOS 0x00
        assert '0x00' in commands, "Missing TOS 0x00 for DSCP 0"
        # DSCP 44 (VA) -> TOS 0xb0
        assert '0xb0' in commands, "Missing TOS 0xb0 for DSCP 44"
        # DSCP 26 (AF31) -> TOS 0x68
        assert '0x68' in commands, "Missing TOS 0x68 for DSCP 26"
        # DSCP 48 (CS6) -> TOS 0xc0
        assert '0xc0' in commands, "Missing TOS 0xc0 for DSCP 48"

    def test_filter_mask(self):
        """All u32 filters must use 0xfc mask to ignore ECN bits."""
        commands = load_commands()
        filter_lines = [l.strip() for l in commands.split('\n')
                        if 'filter' in l and 'u32' in l and 'tos' in l]
        assert len(filter_lines) >= 13, \
            f"Expected >= 13 filter lines, got {len(filter_lines)}"
        for line in filter_lines:
            assert '0xfc' in line, f"Filter missing 0xfc mask: {line}"

    def test_optimized_rates_in_commands(self):
        """Verify optimized (scaled) rates appear in tc commands."""
        commands = load_commands()
        assert 'rate 1600mbit' in commands, \
            "Missing scaled rate 1600mbit for web/db"
        assert 'rate 800mbit' in commands, \
            "Missing scaled rate 800mbit for email"

    def test_command_ordering_per_interface(self):
        """Root qdisc must precede classes, classes must precede filters."""
        commands = load_commands()
        for iface in ['eth0', 'eth1']:
            iface_lines = [l for l in commands.split('\n')
                           if iface in l and l.strip()
                           and 'qdisc del' not in l]
            root_idx = None
            first_class_idx = None
            first_filter_idx = None
            for i, line in enumerate(iface_lines):
                if 'qdisc add' in line and 'root' in line and root_idx is None:
                    root_idx = i
                elif 'class add' in line and first_class_idx is None:
                    first_class_idx = i
                elif 'filter add' in line and first_filter_idx is None:
                    first_filter_idx = i
            if root_idx is not None and first_class_idx is not None:
                assert root_idx < first_class_idx, \
                    f"[{iface}] root qdisc at {root_idx} must precede " \
                    f"first class at {first_class_idx}"
            if first_class_idx is not None and first_filter_idx is not None:
                assert first_class_idx < first_filter_idx, \
                    f"[{iface}] classes at {first_class_idx} must precede " \
                    f"filters at {first_filter_idx}"

    def test_eth1_uses_corrected_default(self):
        """eth1 root qdisc must use the corrected default class."""
        commands = load_commands()
        eth1_root_lines = [l for l in commands.split('\n')
                           if 'eth1' in l and 'qdisc add' in l
                           and 'root' in l]
        assert len(eth1_root_lines) >= 1
        assert 'default 32' in eth1_root_lines[0], \
            f"eth1 root should use default 32, got: {eth1_root_lines[0]}"


class TestNftablesRules:
    """Tests for the nftables DSCP classification ruleset (Part 3)."""

    def test_nft_file_exists(self):
        assert os.path.exists('/app/nft_classify.nft')

    def test_nft_netdev_family(self):
        """Must use netdev table family for tc integration."""
        with open('/app/nft_classify.nft') as f:
            content = f.read()
        assert 'table netdev' in content, \
            "Must use netdev address family"

    def test_nft_both_interfaces(self):
        """Must have rules for both eth0 and eth1."""
        with open('/app/nft_classify.nft') as f:
            content = f.read()
        assert 'eth0' in content and 'eth1' in content, \
            "Must cover both interfaces"

    def test_nft_priority_assignment(self):
        """Must set meta priority for tc class assignment."""
        with open('/app/nft_classify.nft') as f:
            content = f.read()
        assert 'priority' in content, \
            "Must use meta priority for tc classid assignment"

    def test_nft_separate_chains(self):
        """Must have separate classification chains for each interface."""
        with open('/app/nft_classify.nft') as f:
            content = f.read()
        chain_count = content.count('chain ')
        assert chain_count >= 2, \
            f"Expected >= 2 chains (one per interface), got {chain_count}"

    def test_nft_all_leaf_classids(self):
        """All leaf classids from both interfaces must be mapped."""
        with open('/app/nft_classify.nft') as f:
            content = f.read()
        # eth0: 1:11,1:12,1:21,1:22,1:23,1:31,1:32
        # eth1: 1:11,1:12,1:21,1:22,1:31,1:32
        # unique set:
        for classid in ['1:11', '1:12', '1:21', '1:22', '1:23', '1:31', '1:32']:
            assert classid in content, \
                f"Missing classid {classid} in nft rules"

    def test_nft_enough_classid_refs(self):
        """Must have at least 13 classid references (7 eth0 + 6 eth1)."""
        with open('/app/nft_classify.nft') as f:
            content = f.read()
        classid_refs = re.findall(r'1:\d+', content)
        assert len(classid_refs) >= 13, \
            f"Expected >= 13 classid references, got {len(classid_refs)}"

    def test_nft_dscp_keyword(self):
        """Must reference DSCP for packet classification."""
        with open('/app/nft_classify.nft') as f:
            content = f.read().lower()
        assert 'dscp' in content, \
            "Must use DSCP matching for classification"


class TestValidationSummary:

    def test_summary_exists(self):
        assert os.path.exists('/app/validation_summary.txt')

    def test_summary_mentions_violations(self):
        with open('/app/validation_summary.txt') as f:
            content = f.read()
        assert '5' in content, "Summary should mention 5 violations"

    def test_summary_mentions_sla(self):
        with open('/app/validation_summary.txt') as f:
            content = f.read()
        content_lower = content.lower()
        assert 'sla' in content_lower or 'compliance' in content_lower, \
            "Summary should mention SLA compliance"
