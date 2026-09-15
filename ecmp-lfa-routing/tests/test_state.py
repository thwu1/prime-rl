"""
Tests for Network Routing Convergence Audit

"""

import pytest
import json
import os
import sys
sys.path.insert(0, '/app')
from routing_engine import RoutingEngine


# ── Integration tests: topology discovery, visualization, audit report ──


class TestTopologyDiscovery:
    """Verify pcap parsing produced correct topology."""

    def _load(self):
        with open('/app/discovered_topology.json') as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.isfile('/app/discovered_topology.json')

    def test_router_count(self):
        topo = self._load()
        assert set(topo['routers']) == {'A', 'B', 'C', 'D', 'E', 'F'}

    def test_link_count(self):
        topo = self._load()
        assert len(topo['links']) == 16

    def test_specific_links(self):
        topo = self._load()
        links = {(l['src'], l['dst']): l['cost'] for l in topo['links']}
        assert links[('A', 'B')] == 3
        assert links[('B', 'A')] == 3
        assert links[('A', 'D')] == 1
        assert links[('D', 'E')] == 1
        assert links[('E', 'F')] == 2
        assert links[('B', 'E')] == 1
        assert links[('C', 'D')] == 1
        assert links[('A', 'F')] == 6

    def test_no_spurious_links(self):
        """Malformed packets (magic != NL) must not appear."""
        topo = self._load()
        links = {(l['src'], l['dst']): l['cost'] for l in topo['links']}
        for k, v in links.items():
            assert v != 999, f"Spurious link {k} with cost 999 from malformed packet"


class TestVisualization:
    """Verify graphviz output."""

    def test_dot_exists(self):
        assert os.path.isfile('/app/topology.dot')

    def test_dot_has_edges(self):
        with open('/app/topology.dot') as f:
            content = f.read()
        assert 'graph' in content.lower() or 'digraph' in content.lower()
        assert '--' in content or '->' in content

    def test_dot_has_cost_labels(self):
        with open('/app/topology.dot') as f:
            content = f.read()
        assert 'label' in content.lower()

    def test_png_exists(self):
        assert os.path.isfile('/app/topology.png')

    def test_png_valid(self):
        with open('/app/topology.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG'


class TestAuditReport:
    """Verify audit report structure and values."""

    def _load(self):
        with open('/app/audit_report.json') as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.isfile('/app/audit_report.json')

    def test_forwarding_table_costs(self):
        r = self._load()
        ft = r['forwarding_table']
        assert ft['B']['cost'] == 3
        assert ft['C']['cost'] == 2
        assert ft['D']['cost'] == 1
        assert ft['E']['cost'] == 2
        assert ft['F']['cost'] == 4

    def test_ecmp_next_hops(self):
        r = self._load()
        ft = r['forwarding_table']
        assert sorted(ft['B']['primary_next_hops']) == ['B', 'D']
        assert ft['D']['primary_next_hops'] == ['D']
        assert ft['E']['primary_next_hops'] == ['D']

    def test_backup_paths(self):
        r = self._load()
        ft = r['forwarding_table']
        assert sorted(ft['E']['backup_next_hops']['link_protecting']) == ['B', 'F']
        assert sorted(ft['E']['backup_next_hops']['node_protecting']) == ['B', 'F']
        assert sorted(ft['B']['backup_next_hops']['link_protecting']) == ['F']
        assert ft['B']['backup_next_hops']['node_protecting'] == []

    def test_coverage(self):
        r = self._load()
        cov = r['coverage']
        assert cov['link_protecting_pct'] == pytest.approx(100.0)
        assert cov['node_protecting_pct'] == pytest.approx(40.0)
        assert cov['unprotected_destinations'] == []

    def test_policy_compliance(self):
        r = self._load()
        pc = r['policy_compliance']
        assert pc['all_destinations_reachable'] is True
        assert pc['critical_destinations_have_backup'] is True
        assert pc['max_cost_exceeded'] == []


# ── Unit tests: routing engine ──


class TestBasicSPF:
    def test_simple_triangle(self):
        e = RoutingEngine()
        for s, d, c in [('A','B',1), ('B','A',1), ('B','C',1),
                         ('C','B',1), ('A','C',3), ('C','A',3)]:
            e.update_link(s, d, c)
        dist = e.shortest_path_distances('A')
        assert dist['B'] == 1
        assert dist['C'] == 2

    def test_single_directed_link(self):
        e = RoutingEngine()
        e.update_link('X', 'Y', 5)
        assert e.shortest_path_distances('X') == {'Y': 5}
        assert e.shortest_path_distances('Y') == {}

    def test_longer_path_shorter_cost(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 10)
        e.update_link('A', 'C', 1)
        e.update_link('C', 'D', 1)
        e.update_link('D', 'B', 1)
        dist = e.shortest_path_distances('A')
        assert dist['B'] == 3
        assert dist['C'] == 1
        assert dist['D'] == 2

    def test_disconnected_components(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.update_link('C', 'D', 1)
        dist = e.shortest_path_distances('A')
        assert 'B' in dist
        assert 'C' not in dist
        assert 'D' not in dist


class TestECMP:
    def test_diamond_ecmp(self):
        e = RoutingEngine()
        for s, d, c in [('S','A',1),('A','S',1),('S','B',1),('B','S',1),
                         ('A','D',1),('D','A',1),('B','D',1),('D','B',1)]:
            e.update_link(s, d, c)
        nh = e.ecmp_next_hops('S')
        assert nh['A'] == frozenset({'A'})
        assert nh['B'] == frozenset({'B'})
        assert nh['D'] == frozenset({'A', 'B'})

    def test_no_ecmp_different_costs(self):
        e = RoutingEngine()
        for s, d, c in [('S','A',1),('A','S',1),('S','B',1),('B','S',1),
                         ('A','D',1),('D','A',1),('B','D',2),('D','B',2)]:
            e.update_link(s, d, c)
        nh = e.ecmp_next_hops('S')
        assert nh['D'] == frozenset({'A'})

    def test_three_way_ecmp(self):
        e = RoutingEngine()
        for mid in ['M1', 'M2', 'M3']:
            e.update_link('S', mid, 1)
            e.update_link(mid, 'S', 1)
            e.update_link(mid, 'T', 2)
            e.update_link('T', mid, 2)
        nh = e.ecmp_next_hops('S')
        assert nh['T'] == frozenset({'M1', 'M2', 'M3'})

    def test_ecmp_multi_hop_chain(self):
        e = RoutingEngine()
        for s, d, c in [('S','A',1),('A','C',1),('C','D',1),
                         ('S','B',1),('B','D',2),('S','D',5)]:
            e.update_link(s, d, c)
        nh = e.ecmp_next_hops('S')
        assert nh['D'] == frozenset({'A', 'B'})
        assert e.shortest_path_distances('S')['D'] == 3


class TestAsymmetric:
    def test_asymmetric_costs(self):
        e = RoutingEngine()
        e.update_link('X', 'Y', 1)
        e.update_link('Y', 'X', 10)
        e.update_link('Y', 'Z', 1)
        e.update_link('Z', 'Y', 1)
        e.update_link('X', 'Z', 5)
        e.update_link('Z', 'X', 5)

        dist_x = e.shortest_path_distances('X')
        assert dist_x['Y'] == 1
        assert dist_x['Z'] == 2

        nh_x = e.ecmp_next_hops('X')
        assert nh_x['Y'] == frozenset({'Y'})
        assert nh_x['Z'] == frozenset({'Y'})

        dist_y = e.shortest_path_distances('Y')
        assert dist_y['X'] == 6
        assert dist_y['Z'] == 1

        nh_y = e.ecmp_next_hops('Y')
        assert nh_y['X'] == frozenset({'Z'})

    def test_one_way_link(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 3)
        assert e.shortest_path_distances('A') == {'B': 3}
        assert e.shortest_path_distances('B') == {}


class TestLinkOperations:
    def test_update_cost(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 5)
        assert e.shortest_path_distances('A')['B'] == 5
        e.update_link('A', 'B', 2)
        assert e.shortest_path_distances('A')['B'] == 2

    def test_remove_link(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.update_link('B', 'C', 1)
        e.remove_link('A', 'B')
        assert e.shortest_path_distances('A') == {}

    def test_remove_nonexistent_is_noop(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.remove_link('X', 'Y')

    def test_nodes_persist_after_remove(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.remove_link('A', 'B')
        nodes = e.get_nodes()
        assert 'A' in nodes
        assert 'B' in nodes


class TestBackupPaths:
    def test_diamond_with_backup(self):
        e = RoutingEngine()
        for s, d, c in [('S','A',1),('A','S',1),('S','B',1),('B','S',1),
                         ('A','D',1),('D','A',1),('B','D',1),('D','B',1),
                         ('S','E',2),('E','S',2),('E','D',1),('D','E',1)]:
            e.update_link(s, d, c)
        bak = e.compute_backup_nexthops('S')
        assert 'E' in bak['D']['link_protecting']
        assert 'E' in bak['D']['node_protecting']
        assert 'A' not in bak['D']['link_protecting']
        assert 'B' not in bak['D']['link_protecting']

    def test_no_backup_linear(self):
        e = RoutingEngine()
        for s, d, c in [('P','Q',1),('Q','P',1),('Q','R',1),('R','Q',1)]:
            e.update_link(s, d, c)
        bak = e.compute_backup_nexthops('P')
        assert bak['R']['link_protecting'] == frozenset()
        assert bak['Q']['link_protecting'] == frozenset()

    def test_backup_asymmetric(self):
        e = RoutingEngine()
        e.update_link('X', 'Y', 1)
        e.update_link('Y', 'X', 10)
        e.update_link('Y', 'Z', 1)
        e.update_link('Z', 'Y', 1)
        e.update_link('X', 'Z', 5)
        e.update_link('Z', 'X', 5)
        bak = e.compute_backup_nexthops('X')

        assert 'Z' in bak['Z']['link_protecting']
        assert 'Z' in bak['Z']['node_protecting']
        assert 'Z' in bak['Y']['link_protecting']
        assert bak['Y']['node_protecting'] == frozenset()

    def test_six_node_network_backup(self):
        e = RoutingEngine()
        links = [('A','B',3),('A','D',1),('A','F',6),('B','C',4),
                 ('B','E',1),('C','D',1),('D','E',1),('E','F',2)]
        for a, b, c in links:
            e.update_link(a, b, c)
            e.update_link(b, a, c)
        bak = e.compute_backup_nexthops('A')

        assert bak['B']['link_protecting'] == frozenset({'F'})
        assert bak['B']['node_protecting'] == frozenset()

        assert bak['C']['link_protecting'] == frozenset({'B', 'F'})
        assert bak['C']['node_protecting'] == frozenset()

        assert bak['D']['link_protecting'] == frozenset({'B', 'F'})
        assert bak['D']['node_protecting'] == frozenset()

        assert bak['E']['link_protecting'] == frozenset({'B', 'F'})
        assert bak['E']['node_protecting'] == frozenset({'B', 'F'})

        assert bak['F']['link_protecting'] == frozenset({'B', 'F'})
        assert bak['F']['node_protecting'] == frozenset({'B', 'F'})


class TestBackupCoverage:
    def test_full_link_coverage(self):
        e = RoutingEngine()
        links = [('A','B',3),('A','D',1),('A','F',6),('B','C',4),
                 ('B','E',1),('C','D',1),('D','E',1),('E','F',2)]
        for a, b, c in links:
            e.update_link(a, b, c)
            e.update_link(b, a, c)
        cov = e.backup_coverage('A')
        assert cov['link_protecting_pct'] == 100.0
        assert cov['unprotected'] == frozenset()

    def test_zero_coverage_linear(self):
        e = RoutingEngine()
        for s, d, c in [('P','Q',1),('Q','P',1),('Q','R',1),('R','Q',1)]:
            e.update_link(s, d, c)
        cov = e.backup_coverage('P')
        assert cov['link_protecting_pct'] == 0.0
        assert cov['node_protecting_pct'] == 0.0
        assert cov['unprotected'] == frozenset({'Q', 'R'})

    def test_no_destinations_vacuous(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.remove_link('A', 'B')
        cov = e.backup_coverage('A')
        assert cov['link_protecting_pct'] == 100.0
        assert cov['unprotected'] == frozenset()

    def test_node_protecting_pct(self):
        e = RoutingEngine()
        links = [('A','B',3),('A','D',1),('A','F',6),('B','C',4),
                 ('B','E',1),('C','D',1),('D','E',1),('E','F',2)]
        for a, b, c in links:
            e.update_link(a, b, c)
            e.update_link(b, a, c)
        cov = e.backup_coverage('A')
        assert cov['node_protecting_pct'] == pytest.approx(40.0)


class TestForwardingTable:
    def test_basic_table(self):
        e = RoutingEngine()
        for s, d, c in [('A','B',1),('B','A',1),('B','C',1),
                         ('C','B',1),('A','C',3),('C','A',3)]:
            e.update_link(s, d, c)
        table = e.forwarding_table('A')
        assert table['B']['cost'] == 1
        assert table['B']['primary'] == frozenset({'B'})
        assert table['C']['cost'] == 2
        assert table['C']['primary'] == frozenset({'B'})

    def test_table_with_ecmp_and_backup(self):
        e = RoutingEngine()
        links = [('A','B',3),('A','D',1),('A','F',6),('B','C',4),
                 ('B','E',1),('C','D',1),('D','E',1),('E','F',2)]
        for a, b, c in links:
            e.update_link(a, b, c)
            e.update_link(b, a, c)
        table = e.forwarding_table('A')

        assert table['B']['cost'] == 3
        assert table['B']['primary'] == frozenset({'B', 'D'})
        assert table['B']['link_backup'] == frozenset({'F'})

        assert table['D']['cost'] == 1
        assert table['D']['primary'] == frozenset({'D'})

        assert table['E']['cost'] == 2
        assert table['E']['primary'] == frozenset({'D'})
        assert table['E']['node_backup'] == frozenset({'B', 'F'})

        assert table['F']['cost'] == 4
        assert table['F']['primary'] == frozenset({'D'})
        assert table['F']['node_backup'] == frozenset({'B', 'F'})


class TestEventProcessing:
    def test_symmetric_partition_recovery(self):
        e = RoutingEngine()
        events = [
            ('add_symmetric', 'G', 'H', 1),
            ('add_symmetric', 'H', 'I', 1),
            ('add_symmetric', 'I', 'J', 1),
            ('remove_symmetric', 'H', 'I'),
            ('add_symmetric', 'G', 'I', 2),
        ]
        tables = e.process_events(events, 'G')

        assert set(tables[0].keys()) == {'H'}
        assert tables[0]['H']['cost'] == 1

        assert set(tables[1].keys()) == {'H', 'I'}
        assert tables[1]['I']['cost'] == 2

        assert set(tables[2].keys()) == {'H', 'I', 'J'}
        assert tables[2]['J']['cost'] == 3

        assert set(tables[3].keys()) == {'H'}

        assert set(tables[4].keys()) == {'H', 'I', 'J'}
        assert tables[4]['I']['cost'] == 2
        assert tables[4]['I']['primary'] == frozenset({'I'})
        assert tables[4]['J']['cost'] == 3
        assert tables[4]['J']['primary'] == frozenset({'I'})

    def test_complex_event_sequence(self):
        e = RoutingEngine()
        init_links = [('A','B',3),('A','D',1),('A','F',6),('B','C',4),
                      ('B','E',1),('C','D',1),('D','E',1),('E','F',2)]
        for a, b, c in init_links:
            e.update_link(a, b, c)
            e.update_link(b, a, c)

        events = [
            ('remove_symmetric', 'C', 'D'),
            ('add_symmetric', 'C', 'D', 9),
            ('remove_symmetric', 'A', 'D'),
            ('add_symmetric', 'A', 'E', 1),
        ]
        tables = e.process_events(events, 'A')

        assert tables[0]['C']['cost'] == 7
        assert tables[0]['C']['primary'] == frozenset({'B', 'D'})

        assert tables[1]['C']['cost'] == 7

        assert tables[2]['B']['cost'] == 3
        assert tables[2]['B']['primary'] == frozenset({'B'})
        assert tables[2]['D']['cost'] == 5
        assert tables[2]['E']['cost'] == 4
        assert tables[2]['C']['cost'] == 7
        assert tables[2]['F']['cost'] == 6
        assert tables[2]['F']['primary'] == frozenset({'B', 'F'})

        assert tables[3]['E']['cost'] == 1
        assert tables[3]['E']['primary'] == frozenset({'E'})
        assert tables[3]['B']['cost'] == 2
        assert tables[3]['B']['primary'] == frozenset({'E'})
        assert tables[3]['D']['cost'] == 2
        assert tables[3]['F']['cost'] == 3
        assert tables[3]['C']['cost'] == 6

    def test_directed_events(self):
        e = RoutingEngine()
        events = [
            ('add', 'A', 'B', 1),
            ('add', 'B', 'C', 2),
            ('add', 'A', 'C', 10),
            ('remove', 'B', 'C'),
        ]
        tables = e.process_events(events, 'A')

        assert set(tables[0].keys()) == {'B'}
        assert tables[1]['C']['cost'] == 3
        assert tables[2]['C']['cost'] == 3
        assert tables[3]['C']['cost'] == 10
        assert tables[3]['C']['primary'] == frozenset({'C'})


class TestEdgeCases:
    def test_self_not_in_results(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.update_link('B', 'A', 1)
        assert 'A' not in e.shortest_path_distances('A')
        assert 'A' not in e.ecmp_next_hops('A')

    def test_empty_engine(self):
        e = RoutingEngine()
        assert e.shortest_path_distances('X') == {}
        assert e.ecmp_next_hops('X') == {}
        assert e.forwarding_table('X') == {}

    def test_ring_with_crosslink(self):
        e = RoutingEngine()
        nodes = [f'N{i}' for i in range(10)]
        for i in range(10):
            e.update_link(nodes[i], nodes[(i+1) % 10], 1)
            e.update_link(nodes[(i+1) % 10], nodes[i], 1)
        e.update_link('N0', 'N5', 3)
        e.update_link('N5', 'N0', 3)

        dist = e.shortest_path_distances('N0')
        assert dist['N5'] == 3
        assert dist['N1'] == 1
        assert dist['N4'] == 4
        nh = e.ecmp_next_hops('N0')
        assert nh['N4'] == frozenset({'N1', 'N5'})

    def test_get_neighbors(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 3)
        e.update_link('A', 'C', 5)
        assert e.get_neighbors('A') == {'B': 3, 'C': 5}
        assert e.get_neighbors('B') == {}
        assert e.get_neighbors('Z') == {}

    def test_frozenset_types(self):
        e = RoutingEngine()
        e.update_link('A', 'B', 1)
        e.update_link('B', 'A', 1)
        e.update_link('A', 'C', 2)
        e.update_link('C', 'A', 2)
        nh = e.ecmp_next_hops('A')
        assert isinstance(nh['B'], frozenset)
        bak = e.compute_backup_nexthops('A')
        for dest, v in bak.items():
            assert isinstance(v['link_protecting'], frozenset)
            assert isinstance(v['node_protecting'], frozenset)
