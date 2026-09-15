
import json
import os
import pytest

INF = 9999

# Expected final routing tables (phase 8)
EXPECTED_FINAL = {
    "A": {"A": [0, "A"], "B": [5, "B"], "C": [8, "B"], "D": [2, "D"],
           "E": [INF, None], "F": [12, "B"], "G": [13, "B"]},
    "B": {"A": [5, "A"], "B": [0, "B"], "C": [3, "C"], "D": [7, "A"],
           "E": [INF, None], "F": [7, "C"], "G": [8, "C"]},
    "C": {"A": [8, "B"], "B": [3, "B"], "C": [0, "C"], "D": [10, "B"],
           "E": [INF, None], "F": [4, "F"], "G": [5, "F"]},
    "D": {"A": [2, "A"], "B": [7, "A"], "C": [10, "A"], "D": [0, "D"],
           "E": [INF, None], "F": [14, "A"], "G": [15, "A"]},
    "E": {"A": [INF, None], "B": [INF, None], "C": [INF, None], "D": [INF, None],
           "E": [INF, None], "F": [INF, None], "G": [INF, None]},
    "F": {"A": [12, "C"], "B": [7, "C"], "C": [4, "C"], "D": [14, "C"],
           "E": [INF, None], "F": [0, "F"], "G": [1, "G"]},
    "G": {"A": [13, "F"], "B": [8, "F"], "C": [5, "F"], "D": [15, "F"],
           "E": [INF, None], "F": [1, "F"], "G": [0, "G"]},
}

# Expected tables at phase 0 (initial convergence)
EXPECTED_PHASE0 = {
    "A": {"A": [0, "A"], "B": [1, "B"], "C": [4, "B"], "D": [2, "D"],
           "E": [4, "D"], "F": [5, "B"], "G": [8, "B"]},
    "B": {"A": [1, "A"], "B": [0, "B"], "C": [3, "C"], "D": [3, "A"],
           "E": [4, "E"], "F": [4, "C"], "G": [7, "C"]},
    "C": {"A": [4, "B"], "B": [3, "B"], "C": [0, "C"], "D": [4, "F"],
           "E": [2, "F"], "F": [1, "F"], "G": [4, "F"]},
    "D": {"A": [2, "A"], "B": [3, "A"], "C": [4, "E"], "D": [0, "D"],
           "E": [2, "E"], "F": [3, "E"], "G": [6, "E"]},
    "E": {"A": [4, "D"], "B": [4, "B"], "C": [2, "F"], "D": [2, "D"],
           "E": [0, "E"], "F": [1, "F"], "G": [4, "F"]},
    "F": {"A": [5, "C"], "B": [4, "C"], "C": [1, "C"], "D": [3, "E"],
           "E": [1, "E"], "F": [0, "F"], "G": [3, "G"]},
    "G": {"A": [8, "F"], "B": [7, "F"], "C": [4, "F"], "D": [6, "F"],
           "E": [4, "F"], "F": [3, "F"], "G": [0, "G"]},
}

# Expected tables at phase 3 (after crash G)
EXPECTED_PHASE3 = {
    "A": {"A": [0, "A"], "B": [5, "B"], "C": [5, "D"], "D": [2, "D"],
           "E": [3, "D"], "F": [4, "D"], "G": [INF, None]},
    "B": {"A": [5, "A"], "B": [0, "B"], "C": [3, "C"], "D": [5, "E"],
           "E": [4, "E"], "F": [4, "C"], "G": [INF, None]},
    "C": {"A": [5, "F"], "B": [3, "B"], "C": [0, "C"], "D": [3, "F"],
           "E": [2, "F"], "F": [1, "F"], "G": [INF, None]},
    "D": {"A": [2, "A"], "B": [5, "E"], "C": [3, "E"], "D": [0, "D"],
           "E": [1, "E"], "F": [2, "E"], "G": [INF, None]},
    "E": {"A": [3, "D"], "B": [4, "B"], "C": [2, "F"], "D": [1, "D"],
           "E": [0, "E"], "F": [1, "F"], "G": [INF, None]},
    "F": {"A": [4, "E"], "B": [4, "C"], "C": [1, "C"], "D": [2, "E"],
           "E": [1, "E"], "F": [0, "F"], "G": [INF, None]},
    "G": {"A": [INF, None], "B": [INF, None], "C": [INF, None], "D": [INF, None],
           "E": [INF, None], "F": [INF, None], "G": [INF, None]},
}

# Expected tables at phase 6 (after F-G cost set to 1, G revived and reconnected)
EXPECTED_PHASE6 = {
    "A": {"A": [0, "A"], "B": [5, "B"], "C": [8, "B"], "D": [2, "D"],
           "E": [3, "D"], "F": [4, "D"], "G": [5, "D"]},
    "B": {"A": [5, "A"], "B": [0, "B"], "C": [3, "C"], "D": [5, "E"],
           "E": [4, "E"], "F": [5, "E"], "G": [6, "E"]},
    "C": {"A": [8, "B"], "B": [3, "B"], "C": [0, "C"], "D": [6, "F"],
           "E": [5, "F"], "F": [4, "F"], "G": [5, "F"]},
    "D": {"A": [2, "A"], "B": [5, "E"], "C": [6, "E"], "D": [0, "D"],
           "E": [1, "E"], "F": [2, "E"], "G": [3, "E"]},
    "E": {"A": [3, "D"], "B": [4, "B"], "C": [5, "F"], "D": [1, "D"],
           "E": [0, "E"], "F": [1, "F"], "G": [2, "F"]},
    "F": {"A": [4, "E"], "B": [5, "E"], "C": [4, "C"], "D": [2, "E"],
           "E": [1, "E"], "F": [0, "F"], "G": [1, "G"]},
    "G": {"A": [5, "F"], "B": [6, "F"], "C": [5, "F"], "D": [3, "F"],
           "E": [2, "F"], "F": [1, "F"], "G": [0, "G"]},
}

EXPECTED_ROUNDS = [4, 2, 4, 1, 4, 1, 4, 5, 1]


def load_json(path):
    with open(path) as f:
        return json.load(f)


class TestRoutingTables:
    """Verify final routing tables are correct."""

    def test_final_tables_exist(self):
        assert os.path.exists("/app/routing_tables.json"), \
            "routing_tables.json not found"

    def test_final_tables_all_nodes(self):
        tables = load_json("/app/routing_tables.json")
        expected_nodes = {"A", "B", "C", "D", "E", "F", "G"}
        assert set(tables.keys()) == expected_nodes

    def test_final_costs_correct(self):
        tables = load_json("/app/routing_tables.json")
        for src, dests in EXPECTED_FINAL.items():
            for dst, (exp_cost, _) in dests.items():
                actual = tables[src][dst]
                assert actual[0] == exp_cost, \
                    f"Cost {src}->{dst}: expected {exp_cost}, got {actual[0]}"

    def test_final_nexthops_correct(self):
        tables = load_json("/app/routing_tables.json")
        for src, dests in EXPECTED_FINAL.items():
            for dst, (_, exp_nh) in dests.items():
                actual = tables[src][dst]
                assert actual[1] == exp_nh, \
                    f"NextHop {src}->{dst}: expected {exp_nh}, got {actual[1]}"

    def test_crashed_node_all_unreachable(self):
        """E is crashed at the end - verify all its routes are INF/null."""
        tables = load_json("/app/routing_tables.json")
        for dst in ["A", "B", "C", "D", "E", "F", "G"]:
            assert tables["E"][dst] == [INF, None], \
                f"Crashed node E should have [9999, null] for {dst}"

    def test_self_routes(self):
        """Active nodes must have [0, self] self-routes."""
        tables = load_json("/app/routing_tables.json")
        for node in ["A", "B", "C", "D", "F", "G"]:
            assert tables[node][node] == [0, node], \
                f"Self-route for {node} should be [0, '{node}']"


class TestConvergenceLog:
    """Verify the convergence log structure and values."""

    def test_log_exists(self):
        assert os.path.exists("/app/convergence_log.json"), \
            "convergence_log.json not found"

    def test_log_phase_count(self):
        log = load_json("/app/convergence_log.json")
        assert len(log) == 9, \
            f"Expected 9 phases (initial + 8 events), got {len(log)}"

    def test_log_phase_numbers(self):
        log = load_json("/app/convergence_log.json")
        for i, entry in enumerate(log):
            assert entry["phase"] == i, \
                f"Phase {i} has wrong phase number: {entry['phase']}"

    def test_convergence_rounds(self):
        """Verify convergence round counts match expected values."""
        log = load_json("/app/convergence_log.json")
        for i, entry in enumerate(log):
            assert entry["rounds"] == EXPECTED_ROUNDS[i], \
                f"Phase {i}: expected {EXPECTED_ROUNDS[i]} rounds, got {entry['rounds']}"

    def test_phase0_tables(self):
        """Verify initial convergence produces correct routing tables."""
        log = load_json("/app/convergence_log.json")
        tables = log[0]["tables"]
        for src, dests in EXPECTED_PHASE0.items():
            for dst, (exp_cost, exp_nh) in dests.items():
                actual = tables[src][dst]
                assert actual[0] == exp_cost, \
                    f"Phase 0 cost {src}->{dst}: expected {exp_cost}, got {actual[0]}"
                assert actual[1] == exp_nh, \
                    f"Phase 0 nexthop {src}->{dst}: expected {exp_nh}, got {actual[1]}"

    def test_phase3_crash_tables(self):
        """Verify routing tables after crash of node G."""
        log = load_json("/app/convergence_log.json")
        tables = log[3]["tables"]
        for src, dests in EXPECTED_PHASE3.items():
            for dst, (exp_cost, exp_nh) in dests.items():
                actual = tables[src][dst]
                assert actual[0] == exp_cost, \
                    f"Phase 3 cost {src}->{dst}: expected {exp_cost}, got {actual[0]}"
                assert actual[1] == exp_nh, \
                    f"Phase 3 nexthop {src}->{dst}: expected {exp_nh}, got {actual[1]}"

    def test_phase6_revive_tables(self):
        """Verify routing tables after G is revived and reconnected."""
        log = load_json("/app/convergence_log.json")
        tables = log[6]["tables"]
        for src, dests in EXPECTED_PHASE6.items():
            for dst, (exp_cost, exp_nh) in dests.items():
                actual = tables[src][dst]
                assert actual[0] == exp_cost, \
                    f"Phase 6 cost {src}->{dst}: expected {exp_cost}, got {actual[0]}"
                assert actual[1] == exp_nh, \
                    f"Phase 6 nexthop {src}->{dst}: expected {exp_nh}, got {actual[1]}"


class TestPoisonReverse:
    """Verify loop prevention and routing consistency."""

    def test_no_routing_loops_phase0(self):
        """Check no routing loops exist in initial convergence."""
        log = load_json("/app/convergence_log.json")
        tables = log[0]["tables"]
        nodes = ["A", "B", "C", "D", "E", "F", "G"]
        for src in nodes:
            for dst in nodes:
                if src == dst:
                    continue
                cost, nh = tables[src][dst]
                if cost >= INF:
                    continue
                visited = {src}
                cur = nh
                hops = 0
                while cur != dst and cur is not None and hops < 10:
                    assert cur not in visited, \
                        f"Routing loop detected: {src}->{dst} loops at {cur}"
                    visited.add(cur)
                    next_cost, next_nh = tables[cur][dst]
                    cur = next_nh
                    hops += 1
                assert hops < 10, \
                    f"Path {src}->{dst} too long (>10 hops), possible loop"

    def test_no_routing_loops_final(self):
        """Check no routing loops exist in final state."""
        tables = load_json("/app/routing_tables.json")
        active_nodes = ["A", "B", "C", "D", "F", "G"]
        for src in active_nodes:
            for dst in active_nodes:
                if src == dst:
                    continue
                cost, nh = tables[src][dst]
                if cost >= INF:
                    continue
                visited = {src}
                cur = nh
                hops = 0
                while cur != dst and cur is not None and hops < 10:
                    assert cur not in visited, \
                        f"Routing loop detected: {src}->{dst} loops at {cur}"
                    visited.add(cur)
                    next_cost, next_nh = tables[cur][dst]
                    cur = next_nh
                    hops += 1
                assert hops < 10, \
                    f"Path {src}->{dst} too long (>10 hops), possible loop"

    def test_symmetry_of_costs(self):
        """Cost from A to B should equal cost from B to A."""
        tables = load_json("/app/routing_tables.json")
        nodes = ["A", "B", "C", "D", "E", "F", "G"]
        for i, n1 in enumerate(nodes):
            for n2 in nodes[i+1:]:
                c1 = tables[n1][n2][0]
                c2 = tables[n2][n1][0]
                assert c1 == c2, \
                    f"Asymmetric cost: {n1}->{n2}={c1}, {n2}->{n1}={c2}"


class TestModuleInterface:
    """Verify the simulator works correctly on an independent topology."""

    def _load_simulator(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dv_router", "/app/dv_router.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.DVSimulator

    def test_secondary_initial_convergence(self):
        """Test on a 4-node topology with equal-cost path ties."""
        DVSim = self._load_simulator()
        nodes = ["P", "Q", "R", "S"]
        links = [
            {"src": "P", "dst": "Q", "cost": 2},
            {"src": "Q", "dst": "R", "cost": 3},
            {"src": "R", "dst": "S", "cost": 1},
            {"src": "P", "dst": "S", "cost": 4},
        ]
        sim = DVSim(nodes, links)
        sim.converge()
        tables = sim.get_tables()

        # P->R: P-Q-R=5 and P-S-R=5, tie resolved to Q (Q < S)
        assert tables["P"]["R"] == [5, "Q"], \
            f"P->R: expected [5, 'Q'], got {tables['P']['R']}"
        # R->P: R-Q-P=5 and R-S-P=5, tie resolved to Q (Q < S)
        assert tables["R"]["P"] == [5, "Q"], \
            f"R->P: expected [5, 'Q'], got {tables['R']['P']}"
        # Q->S: Q-R-S=4 < Q-P-S=6
        assert tables["Q"]["S"] == [4, "R"], \
            f"Q->S: expected [4, 'R'], got {tables['Q']['S']}"
        # S->Q: S-R-Q=4 < S-P-Q=6
        assert tables["S"]["Q"] == [4, "R"], \
            f"S->Q: expected [4, 'R'], got {tables['S']['Q']}"
        # Direct links
        assert tables["P"]["Q"] == [2, "Q"]
        assert tables["P"]["S"] == [4, "S"]
        assert tables["Q"]["R"] == [3, "R"]
        assert tables["R"]["S"] == [1, "S"]

    def test_secondary_link_removal(self):
        """Test event processing with link removal on secondary topology."""
        DVSim = self._load_simulator()
        nodes = ["P", "Q", "R", "S"]
        links = [
            {"src": "P", "dst": "Q", "cost": 2},
            {"src": "Q", "dst": "R", "cost": 3},
            {"src": "R", "dst": "S", "cost": 1},
            {"src": "P", "dst": "S", "cost": 4},
        ]
        sim = DVSim(nodes, links)
        sim.converge()
        sim.apply_event({"type": "update", "src": "R", "dst": "S", "cost": 9999})
        sim.converge()
        tables = sim.get_tables()

        # After removing R-S, paths reroute through P
        assert tables["Q"]["S"] == [6, "P"], \
            f"After R-S removal, Q->S: expected [6, 'P'], got {tables['Q']['S']}"
        assert tables["R"]["S"] == [9, "Q"], \
            f"After R-S removal, R->S: expected [9, 'Q'], got {tables['R']['S']}"
        assert tables["S"]["R"] == [9, "P"], \
            f"After R-S removal, S->R: expected [9, 'P'], got {tables['S']['R']}"
        assert tables["S"]["Q"] == [6, "P"], \
            f"After R-S removal, S->Q: expected [6, 'P'], got {tables['S']['Q']}"

    def test_secondary_crash_and_revive(self):
        """Test crash and revive handling on a 3-node topology."""
        DVSim = self._load_simulator()
        nodes = ["M", "N", "O"]
        links = [
            {"src": "M", "dst": "N", "cost": 1},
            {"src": "N", "dst": "O", "cost": 2},
            {"src": "M", "dst": "O", "cost": 4},
        ]
        sim = DVSim(nodes, links)
        sim.converge()
        tables = sim.get_tables()

        # M->O: M-N-O=3 < M-O=4
        assert tables["M"]["O"] == [3, "N"], \
            f"M->O: expected [3, 'N'], got {tables['M']['O']}"

        # Crash N
        sim.apply_event({"type": "crash", "node": "N"})
        sim.converge()
        tables = sim.get_tables()

        assert tables["M"]["O"] == [4, "O"], \
            f"After N crash, M->O: expected [4, 'O'], got {tables['M']['O']}"
        assert tables["M"]["N"] == [INF, None], \
            f"After N crash, M->N: expected [9999, null], got {tables['M']['N']}"
        for dst in ["M", "N", "O"]:
            assert tables["N"][dst] == [INF, None], \
                f"Crashed N->{dst} should be [9999, null], got {tables['N'][dst]}"

        # Revive N and restore link
        sim.apply_event({"type": "revive", "node": "N"})
        sim.converge()
        tables_after_revive = sim.get_tables()

        # N is back but has no links yet
        assert tables_after_revive["N"]["N"] == [0, "N"]
        assert tables_after_revive["N"]["M"] == [INF, None]

        # Restore M-N link
        sim.apply_event({"type": "update", "src": "M", "dst": "N", "cost": 1})
        sim.converge()
        tables_restored = sim.get_tables()

        assert tables_restored["M"]["N"] == [1, "N"]
        assert tables_restored["N"]["M"] == [1, "M"]
