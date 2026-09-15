"""
OSPF multi-area network design validation tests.

Verifies that all OSPF adjacencies form, area types are correct,
route summarization is configured, costs are set, external routes
are properly filtered, and totally stub isolation is enforced.
"""

import sys
sys.path.insert(0, '/app')

from ospf_checker import OSPFValidator  # noqa: E402

_cached_report = None


def _report():
    global _cached_report
    if _cached_report is None:
        v = OSPFValidator('/app/configs', '/app/topology.json')
        _cached_report = v.validate()
    return _cached_report


# -- Adjacency tests (all 6 links must reach FULL) --------------------

class TestOSPFAdjacencies:
    def test_r1_r2_full(self):
        assert _report()['adjacencies']['R1-R2']['status'] == 'FULL'

    def test_r2_r3_full(self):
        assert _report()['adjacencies']['R2-R3']['status'] == 'FULL'

    def test_r1_r4_full(self):
        assert _report()['adjacencies']['R1-R4']['status'] == 'FULL'

    def test_r2_r5_full(self):
        assert _report()['adjacencies']['R2-R5']['status'] == 'FULL'

    def test_r4_r5_full(self):
        assert _report()['adjacencies']['R4-R5']['status'] == 'FULL'

    def test_r3_r6_full(self):
        assert _report()['adjacencies']['R3-R6']['status'] == 'FULL'


# -- Area type tests ---------------------------------------------------

class TestAreaTypes:
    def test_area0_normal(self):
        at = _report()['area_types']['0']
        for router, info in at['routers'].items():
            assert info['correct'], \
                f"{router} area 0 wrong: {info['configured']}"

    def test_area1_totally_stub(self):
        at = _report()['area_types']['1']
        for router, info in at['routers'].items():
            assert info['correct'], \
                f"{router} area 1 wrong: {info['configured']}"

    def test_area2_nssa(self):
        at = _report()['area_types']['2']
        for router, info in at['routers'].items():
            assert info['correct'], \
                f"{router} area 2 wrong: {info['configured']}"


# -- Route summarization tests ----------------------------------------

class TestSummarization:
    def test_r1_area1_summary(self):
        s = _report()['summarization']
        assert s['R1_area1_10.1.0.0/16']['present'], \
            "R1 missing area 1 range 10.1.0.0/16"

    def test_r2_area1_summary(self):
        s = _report()['summarization']
        assert s['R2_area1_10.1.0.0/16']['present'], \
            "R2 missing area 1 range 10.1.0.0/16"

    def test_r3_area2_summary(self):
        s = _report()['summarization']
        assert s['R3_area2_10.2.0.0/16']['present'], \
            "R3 missing area 2 range 10.2.0.0/16"


# -- OSPF cost tests ---------------------------------------------------

class TestCosts:
    def test_r1_r4_cost_100(self):
        c = _report()['costs']['R1_r1-r4']
        assert c['correct'], \
            f"R1 r1-r4 cost: expected {c['expected']}, got {c['actual']}"

    def test_r4_r1_cost_100(self):
        c = _report()['costs']['R4_r4-r1']
        assert c['correct'], \
            f"R4 r4-r1 cost: expected {c['expected']}, got {c['actual']}"


# -- Reachability tests ------------------------------------------------

class TestLoopbackReachability:
    def test_r1_to_r4(self):
        assert _report()['loopback_reachability']['R1->R4'] is True

    def test_r1_to_r6(self):
        assert _report()['loopback_reachability']['R1->R6'] is True

    def test_r4_to_r6(self):
        assert _report()['loopback_reachability']['R4->R6'] is True

    def test_r6_to_r1(self):
        assert _report()['loopback_reachability']['R6->R1'] is True

    def test_r6_to_r4(self):
        assert _report()['loopback_reachability']['R6->R4'] is True

    def test_r5_to_r3(self):
        assert _report()['loopback_reachability']['R5->R3'] is True


# -- External route redistribution tests -------------------------------

class TestExternalRoutes:
    def test_172_16_0_permitted(self):
        ext = _report()['external_routes']['172.16.0.0/24']
        assert ext['permitted'] is True, \
            "172.16.0.0/24 should be permitted"

    def test_172_16_1_permitted(self):
        ext = _report()['external_routes']['172.16.1.0/24']
        assert ext['permitted'] is True, \
            "172.16.1.0/24 should be permitted"

    def test_172_16_2_denied(self):
        ext = _report()['external_routes']['172.16.2.0/24']
        assert ext['permitted'] is False, \
            "172.16.2.0/24 should be denied by route filter"

    def test_172_16_0_visible_on_backbone(self):
        ext = _report()['external_routes']['172.16.0.0/24']
        for r in ['R1', 'R2', 'R3']:
            assert r in ext['visible_on'], \
                f"172.16.0.0/24 not visible on {r}"

    def test_172_16_1_visible_on_backbone(self):
        ext = _report()['external_routes']['172.16.1.0/24']
        for r in ['R1', 'R2', 'R3']:
            assert r in ext['visible_on'], \
                f"172.16.1.0/24 not visible on {r}"

    def test_external_blocked_in_totally_stub(self):
        """Routers in totally stub area must NOT see external routes."""
        for prefix in ['172.16.0.0/24', '172.16.1.0/24']:
            ext = _report()['external_routes'][prefix]
            for r in ['R4', 'R5']:
                assert r not in ext['visible_on'], \
                    f"{prefix} must not be visible on {r} (totally stub)"
