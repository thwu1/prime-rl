"""BGP route analyzer verification tests.

"""
import json
import sys
import pytest

sys.path.insert(0, "/app")
from bgp_analyzer import select_best_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


def _r(results, qid):
    """Get result for query id, accepting both str and int keys."""
    return results.get(str(qid), results.get(qid))


def _mk(
    weight=0, local_pref=100, locally_originated=False,
    local_origin_type=None,
    as_path=None, origin="igp", med=0, path_source="ebgp",
    igp_metric=0, router_id="1.1.1.1", originator_id=None,
    cluster_list=None, neighbor_address="10.0.0.1",
    is_valid=True, arrival_order=0,
):
    """Create a route dict with sensible defaults."""
    if as_path is None:
        as_path = [{"type": "AS_SEQUENCE", "asns": [200]}]
    if cluster_list is None:
        cluster_list = []
    return {
        "weight": weight,
        "local_pref": local_pref,
        "locally_originated": locally_originated,
        "local_origin_type": local_origin_type,
        "as_path": as_path,
        "origin": origin,
        "med": med,
        "path_source": path_source,
        "igp_metric": igp_metric,
        "router_id": router_id,
        "originator_id": originator_id,
        "cluster_list": cluster_list,
        "neighbor_address": neighbor_address,
        "is_valid": is_valid,
        "arrival_order": arrival_order,
    }


CFG_DEFAULT = {}
CFG_COMPARE_RID = {"compare_routerid": True}
CFG_ALWAYS_MED = {"always_compare_med": True, "compare_routerid": True}
CFG_DET_MED = {"deterministic_med": True, "compare_routerid": True}
CFG_MED_WORST = {"med_missing_as_worst": True, "compare_routerid": True}
CFG_CONFED_MED = {"med_confed": True, "compare_routerid": True}
CFG_IGNORE_ASPATH = {"as_path_ignore": True, "compare_routerid": True}


# ===================================================================
# Part 1: Validate /app/results.json against the database queries
# ===================================================================

class TestResultsJson:
    """Validate that results.json has correct best-route answers."""

    def test_results_file_exists_and_parseable(self):
        results = _load_results()
        assert isinstance(results, dict), "results.json must be a JSON object"
        assert len(results) >= 20, "results.json must contain at least 20 entries"

    def test_q01_weight(self):
        assert _r(_load_results(), 1) == 3

    def test_q02_localpref_asset(self):
        assert _r(_load_results(), 2) == 5

    def test_q03_confed_ebgp(self):
        assert _r(_load_results(), 3) == 9

    def test_q04_med_standard(self):
        assert _r(_load_results(), 4) == 12

    def test_q05_med_compare_rid(self):
        assert _r(_load_results(), 5) == 12

    def test_q06_always_compare_med(self):
        assert _r(_load_results(), 6) == 11

    def test_q07_deterministic_med(self):
        assert _r(_load_results(), 7) == 11

    def test_q08_med_null_zero(self):
        assert _r(_load_results(), 8) == 13

    def test_q09_med_missing_worst(self):
        assert _r(_load_results(), 9) == 15

    def test_q10_originator_cluster(self):
        assert _r(_load_results(), 10) == 17

    def test_q11_med_confed(self):
        assert _r(_load_results(), 11) == 20

    def test_q12_no_med_confed(self):
        assert _r(_load_results(), 12) == 19

    def test_q13_aspath_normal(self):
        assert _r(_load_results(), 13) == 23

    def test_q14_aspath_ignore(self):
        assert _r(_load_results(), 14) == 22

    def test_q15_oldest_path(self):
        assert _r(_load_results(), 15) == 24

    def test_q16_compare_routerid(self):
        assert _r(_load_results(), 16) == 25

    def test_q17_locally_originated(self):
        assert _r(_load_results(), 17) == 28

    def test_q18_pcap_compare_rid(self):
        """PCAP routes for 10.11.0.0/24 with compare_rid:
        Route 30 (AS100, MED200), Route 31 (AS200, MED50), Route 32 (AS100, MED75).
        Same AS(100) routes: MED 200 vs 75 → route 32 wins."""
        assert _r(_load_results(), 18) == 32

    def test_q19_pcap_always_med(self):
        """PCAP routes with always_compare_med: lowest MED wins.
        MED 200 vs 50 vs 75 → route 31 (MED 50)."""
        assert _r(_load_results(), 19) == 31

    def test_q20_pcap_deterministic_med(self):
        """PCAP routes with deterministic_med:
        Group AS100={30(MED200),32(MED75)} → winner 32.
        Group AS200={31(MED50)} → winner 31.
        Compare winners: diff AS, no MED. rid 10.0.1.2 < 10.0.1.3 → route 31."""
        assert _r(_load_results(), 20) == 31


# ===================================================================
# Part 2: Test select_best_path on independent generated scenarios
# ===================================================================

class TestSelectBestPathAlgorithm:
    """Test the select_best_path function on generated scenarios."""

    # --- Edge cases ---

    def test_no_routes(self):
        assert select_best_path([], {}) == -1

    def test_all_invalid(self):
        routes = [
            _mk(weight=999, is_valid=False),
            _mk(weight=888, is_valid=False),
        ]
        assert select_best_path(routes, {}) == -1

    def test_single_valid(self):
        routes = [_mk(is_valid=True)]
        assert select_best_path(routes, {}) == 0

    # --- Step 1: Weight ---

    def test_weight_higher_wins(self):
        routes = [
            _mk(weight=50, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(weight=300, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 2: Local-pref ---

    def test_localpref_null_defaults_100(self):
        routes = [
            _mk(local_pref=None, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(local_pref=200, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 3: Locally originated ---

    def test_locally_originated_beats_learned(self):
        routes = [
            _mk(locally_originated=True, local_origin_type="network",
                 as_path=[], path_source="ibgp",
                 router_id="9.9.9.9", neighbor_address="10.0.0.1"),
            _mk(locally_originated=False, path_source="ebgp",
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 0

    def test_network_over_aggregate(self):
        routes = [
            _mk(locally_originated=True, local_origin_type="aggregate",
                 as_path=[], path_source="ibgp",
                 router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(locally_originated=True, local_origin_type="network",
                 as_path=[], path_source="ibgp",
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 4: AS-path length ---

    def test_shorter_aspath_wins(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [100, 200, 300]}],
                 router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [400]}],
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    def test_asset_counts_as_one(self):
        routes = [
            _mk(as_path=[{"type": "AS_SET", "asns": [1, 2, 3, 4, 5]}],
                 router_id="2.2.2.2", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [100, 200]}],
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # AS_SET=1 < AS_SEQ=2
        assert select_best_path(routes, CFG_COMPARE_RID) == 0

    def test_confed_seq_not_counted(self):
        routes = [
            _mk(as_path=[
                {"type": "AS_CONFED_SEQUENCE", "asns": [65001, 65002, 65003]},
                {"type": "AS_SEQUENCE", "asns": [100]},
            ], path_source="confed_ebgp",
                router_id="5.5.5.5", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200, 300]}],
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # Route 0: length=1 (confed not counted). Route 1: length=2.
        assert select_best_path(routes, CFG_COMPARE_RID) == 0

    def test_confed_set_not_counted(self):
        routes = [
            _mk(as_path=[
                {"type": "AS_CONFED_SET", "asns": [65001, 65002]},
                {"type": "AS_SEQUENCE", "asns": [100]},
            ], path_source="confed_ebgp",
                router_id="3.3.3.3", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200, 300]}],
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # Route 0: length=1. Route 1: length=2. Route 0 wins.
        assert select_best_path(routes, CFG_COMPARE_RID) == 0

    def test_aspath_ignore(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [100, 200, 300]}],
                 router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [400]}],
                 origin="egp",
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # Without ignore: route 1 wins (shorter path). With ignore: path length skipped.
        # origin: igp < egp → route 0 wins.
        assert select_best_path(routes, CFG_IGNORE_ASPATH) == 0

    # --- Step 5: Origin ---

    def test_origin_igp_over_egp(self):
        routes = [
            _mk(origin="egp", router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(origin="igp", router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    def test_origin_egp_over_incomplete(self):
        routes = [
            _mk(origin="incomplete", router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(origin="egp", router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 6: MED ---

    def test_med_same_neighbor_as(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200, 300]}],
                 med=500, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200, 400]}],
                 med=100, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # Same first AS (200) → MED compared. 100 < 500 → route 1.
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    def test_med_different_as_not_compared(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=999, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [300]}],
                 med=1, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # Different first AS → MED NOT compared. Falls to router_id: 1<2 → route 0.
        assert select_best_path(routes, CFG_COMPARE_RID) == 0

    def test_always_compare_med(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=999, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [300]}],
                 med=1, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # always_compare_med → MED compared across different ASes. 1 < 999 → route 1.
        assert select_best_path(routes, CFG_ALWAYS_MED) == 1

    def test_med_null_default_zero(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=50, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=None, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # Same AS → MED compared. None→0 < 50 → route 1.
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    def test_med_missing_as_worst(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=50, router_id="2.2.2.2", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=None, router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # med_missing_as_worst: None → 4294967295. 50 < max → route 0.
        assert select_best_path(routes, CFG_MED_WORST) == 0

    def test_med_confed_only_paths(self):
        routes = [
            _mk(as_path=[{"type": "AS_CONFED_SEQUENCE", "asns": [65001]}],
                 med=200, path_source="confed_ebgp",
                 router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_CONFED_SEQUENCE", "asns": [65002]}],
                 med=50, path_source="confed_ebgp",
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # Both confed-only, med_confed enabled → MED compared. 50 < 200 → route 1.
        assert select_best_path(routes, CFG_CONFED_MED) == 1

    def test_med_confed_not_applied_to_mixed(self):
        routes = [
            _mk(as_path=[
                {"type": "AS_CONFED_SEQUENCE", "asns": [65001]},
                {"type": "AS_SEQUENCE", "asns": [200]},
            ], med=999, path_source="confed_ebgp",
                router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[
                {"type": "AS_CONFED_SEQUENCE", "asns": [65002]},
                {"type": "AS_SEQUENCE", "asns": [300]},
            ], med=1, path_source="confed_ebgp",
                router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # NOT confed-only (has AS_SEQUENCE). Different first AS. MED NOT compared.
        # Falls to router_id: 1 < 2 → route 0.
        assert select_best_path(routes, CFG_CONFED_MED) == 0

    # --- Step 7: eBGP > iBGP ---

    def test_ebgp_over_ibgp(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ebgp",
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    def test_confed_treated_as_internal(self):
        routes = [
            _mk(as_path=[
                {"type": "AS_CONFED_SEQUENCE", "asns": [65001]},
                {"type": "AS_SEQUENCE", "asns": [200]},
            ], path_source="confed_ebgp",
                router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ebgp",
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        # confed_ebgp is internal; ebgp wins.
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 8: IGP metric ---

    def test_igp_metric_lower_wins(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 igp_metric=100, router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 igp_metric=50, router_id="2.2.2.2", neighbor_address="10.0.0.2"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 10: Oldest path ---

    def test_oldest_ebgp_path_wins(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ebgp", arrival_order=0,
                 router_id="9.9.9.9", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [300]}],
                 path_source="ebgp", arrival_order=1,
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # compare_routerid=false → oldest path applies. Both eBGP, diff rid.
        assert select_best_path(routes, CFG_DEFAULT) == 0

    def test_compare_routerid_skips_oldest(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ebgp", arrival_order=0,
                 router_id="9.9.9.9", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [300]}],
                 path_source="ebgp", arrival_order=1,
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # compare_routerid=true → skip oldest → router_id: 1 < 9 → route 1.
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    def test_oldest_path_not_ibgp(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp", arrival_order=0,
                 router_id="9.9.9.9", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp", arrival_order=1,
                 router_id="1.1.1.1", neighbor_address="10.0.0.2"),
        ]
        # Both iBGP → oldest path does not apply. router_id: 1 < 9 → route 1.
        assert select_best_path(routes, CFG_DEFAULT) == 1

    def test_oldest_skipped_same_effective_rid(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ebgp", arrival_order=0,
                 router_id="5.5.5.5", neighbor_address="192.168.1.2"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [300]}],
                 path_source="ebgp", arrival_order=1,
                 router_id="5.5.5.5", neighbor_address="192.168.1.1"),
        ]
        # Same router_id → skip oldest → router_id same → cluster same →
        # neighbor: 192.168.1.1 < 192.168.1.2 → route 1.
        assert select_best_path(routes, CFG_DEFAULT) == 1

    # --- Step 11: Router ID with originator_id ---

    def test_originator_id_replaces_router_id(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="1.1.1.1", originator_id="8.8.8.8",
                 cluster_list=["10.0.0.100"],
                 neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="9.9.9.9", originator_id="2.2.2.2",
                 cluster_list=["10.0.0.200"],
                 neighbor_address="10.0.0.2"),
        ]
        # originator_id used: 8.8.8.8 vs 2.2.2.2 → route 1 (lower originator).
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 12: Cluster list ---

    def test_shorter_cluster_list_wins(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="1.1.1.1", originator_id="5.5.5.5",
                 cluster_list=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
                 neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="2.2.2.2", originator_id="5.5.5.5",
                 cluster_list=["10.0.0.4"],
                 neighbor_address="10.0.0.2"),
        ]
        # Same effective rid (5.5.5.5). Cluster: 3 vs 1 → route 1.
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Step 13: Neighbor address ---

    def test_lower_neighbor_address_wins(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="5.5.5.5",
                 neighbor_address="192.168.1.2"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 path_source="ibgp",
                 router_id="5.5.5.5",
                 neighbor_address="192.168.1.1"),
        ]
        assert select_best_path(routes, CFG_COMPARE_RID) == 1

    # --- Deterministic MED ---

    def test_deterministic_med_changes_result(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [100]}],
                 med=150, router_id="1.1.1.1",
                 neighbor_address="10.0.0.1", arrival_order=0),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200]}],
                 med=50, router_id="3.3.3.3",
                 neighbor_address="10.0.0.2", arrival_order=1),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [100]}],
                 med=50, router_id="4.4.4.4",
                 neighbor_address="10.0.0.3", arrival_order=2),
        ]
        # Standard (compare_rid): 0 vs 1 → diff AS, no MED, rid 1<3 → 0 wins.
        #   0 vs 2 → same AS(100), MED 150 vs 50 → 2 wins. Result: 2.
        assert select_best_path(routes, CFG_COMPARE_RID) == 2

        # det-med: group AS100={0,2}, AS200={1}
        #   AS100 winner: MED 150 vs 50 → route 2.
        #   Compare route 2(AS100,rid=4.4.4.4) vs route 1(AS200,rid=3.3.3.3):
        #     diff AS, no always_compare_med → MED not compared.
        #     rid 3<4 → route 1 wins.
        assert select_best_path(routes, CFG_DET_MED) == 1

    def test_deterministic_med_ebgp_over_confed(self):
        routes = [
            _mk(as_path=[
                {"type": "AS_CONFED_SEQUENCE", "asns": [65001]},
                {"type": "AS_SEQUENCE", "asns": [100]},
            ], med=200, path_source="confed_ebgp",
                router_id="1.1.1.1", neighbor_address="10.0.0.1"),
            _mk(as_path=[
                {"type": "AS_CONFED_SEQUENCE", "asns": [65002]},
                {"type": "AS_SEQUENCE", "asns": [100]},
            ], med=50, path_source="confed_ebgp",
                router_id="2.2.2.2", neighbor_address="10.0.0.2"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [300]}],
                 med=10, path_source="ebgp",
                 router_id="3.3.3.3", neighbor_address="10.0.0.3"),
        ]
        # det-med groups: AS100={0,1}, AS300={2}
        # AS100 group: same AS → MED compared. 200 vs 50 → route 1.
        # Compare route 1 (confed_ebgp) vs route 2 (ebgp):
        #   diff AS, MED not compared. Step 7: ebgp > confed → route 2 wins.
        assert select_best_path(routes, CFG_DET_MED) == 2

    # --- Invalid routes filtering ---

    def test_invalid_routes_skipped(self):
        routes = [
            _mk(weight=32768, is_valid=False, router_id="1.1.1.1",
                 neighbor_address="10.0.0.1"),
            _mk(weight=0, is_valid=True, router_id="2.2.2.2",
                 neighbor_address="10.0.0.2"),
            _mk(weight=500, is_valid=False, router_id="3.3.3.3",
                 neighbor_address="10.0.0.3"),
        ]
        assert select_best_path(routes, {}) == 1

    # --- Multi-step complex ---

    def test_complex_multi_step(self):
        routes = [
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [200, 300]}],
                 origin="igp", path_source="ibgp", igp_metric=20,
                 router_id="3.3.3.3", neighbor_address="10.0.0.1"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [400]}],
                 origin="egp", path_source="ebgp", igp_metric=10,
                 router_id="2.2.2.2", neighbor_address="10.0.0.2"),
            _mk(as_path=[{"type": "AS_SEQUENCE", "asns": [500]}],
                 origin="igp", path_source="ebgp", igp_metric=5,
                 router_id="1.1.1.1", neighbor_address="10.0.0.3"),
        ]
        # path length: 2, 1, 1. Route 0 eliminated.
        # Among 1 and 2: origin egp vs igp → route 2 wins.
        assert select_best_path(routes, CFG_COMPARE_RID) == 2
