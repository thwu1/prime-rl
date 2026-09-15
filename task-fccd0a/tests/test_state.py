
import sys
import time
import json
import struct
import pytest

sys.path.insert(0, "/app")

from baseline_classifier import BaselineClassifier

RULESET_PATH = "/app/firewall.nft"
PCAP_PATH = "/app/traffic.pcap"
ANALYSIS_PATH = "/app/ruleset_analysis.json"


# === Ground truth computation utilities ===

def _ip_to_int(ip_str):
    parts = ip_str.split(".")
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def _cidrs_overlap(cidr_a, cidr_b):
    net_a, plen_a = cidr_a.rsplit("/", 1)
    net_b, plen_b = cidr_b.rsplit("/", 1)
    plen_a, plen_b = int(plen_a), int(plen_b)
    if plen_a == 0 or plen_b == 0:
        return True
    a, b = _ip_to_int(net_a), _ip_to_int(net_b)
    shift = 32 - min(plen_a, plen_b)
    return (a >> shift) == (b >> shift)


def _cidr_contains(outer, inner):
    net_o, plen_o = outer.rsplit("/", 1)
    net_i, plen_i = inner.rsplit("/", 1)
    plen_o, plen_i = int(plen_o), int(plen_i)
    if plen_o == 0:
        return True
    if plen_i < plen_o:
        return False
    o, i = _ip_to_int(net_o), _ip_to_int(net_i)
    shift = 32 - plen_o
    return (o >> shift) == (i >> shift)


def _rule_is_superset(ra, rb):
    if not _cidr_contains(ra["src_ip"], rb["src_ip"]):
        return False
    if not _cidr_contains(ra["dst_ip"], rb["dst_ip"]):
        return False
    if not (ra["src_port_min"] <= rb["src_port_min"]
            and rb["src_port_max"] <= ra["src_port_max"]):
        return False
    if not (ra["dst_port_min"] <= rb["dst_port_min"]
            and rb["dst_port_max"] <= ra["dst_port_max"]):
        return False
    if ra["protocol"] != "any" and ra["protocol"] != rb["protocol"]:
        return False
    return True


def _rules_overlap(ra, rb):
    if not _cidrs_overlap(ra["src_ip"], rb["src_ip"]):
        return False
    if not _cidrs_overlap(ra["dst_ip"], rb["dst_ip"]):
        return False
    if ra["src_port_max"] < rb["src_port_min"] or rb["src_port_max"] < ra["src_port_min"]:
        return False
    if ra["dst_port_max"] < rb["dst_port_min"] or rb["dst_port_max"] < ra["dst_port_min"]:
        return False
    pa, pb = ra["protocol"], rb["protocol"]
    if pa != "any" and pb != "any" and pa != pb:
        return False
    return True


def read_packets_from_pcap(path):
    """Parse raw-IPv4 pcap and extract packet dicts."""
    packets = []
    with open(path, 'rb') as f:
        magic, vmaj, vmin, _, _, snaplen, linktype = struct.unpack(
            '<IHHiIII', f.read(24))
        assert magic == 0xa1b2c3d4, f"Not a pcap file: {magic:#x}"
        assert linktype == 101, f"Expected raw IP linktype (101), got {linktype}"

        while True:
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', hdr)
            data = f.read(incl_len)
            if len(data) < 20:
                continue

            ihl = (data[0] & 0x0f) * 4
            proto_num = data[9]
            src_ip = f"{data[12]}.{data[13]}.{data[14]}.{data[15]}"
            dst_ip = f"{data[16]}.{data[17]}.{data[18]}.{data[19]}"

            transport = data[ihl:]
            if len(transport) < 4:
                continue
            src_port = struct.unpack('!H', transport[0:2])[0]
            dst_port = struct.unpack('!H', transport[2:4])[0]

            proto_name = ("tcp" if proto_num == 6
                          else "udp" if proto_num == 17
                          else "other")

            packets.append({
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "src_port": src_port,
                "dst_port": dst_port,
                "protocol": proto_name
            })

    return packets


@pytest.fixture(scope="module")
def packets():
    return read_packets_from_pcap(PCAP_PATH)


@pytest.fixture(scope="module")
def baseline_results(packets):
    baseline = BaselineClassifier(RULESET_PATH)
    results = []
    for pkt in packets:
        results.append(baseline.classify(pkt))
    return results


@pytest.fixture(scope="module")
def ground_truth():
    """Compute ground truth from the ruleset — no pre-stored answer files."""
    baseline = BaselineClassifier(RULESET_PATH)
    rules = baseline.rules

    # Unreachable: rules fully subsumed by an earlier rule
    unreachable = []
    for j in range(len(rules)):
        for i in range(j):
            if _rule_is_superset(rules[i], rules[j]):
                unreachable.append(rules[j]["id"])
                break
    unreachable.sort()

    # Ordering constraints: overlapping rules with different actions
    constraints = []
    for i in range(len(rules)):
        for j in range(i + 1, len(rules)):
            if rules[i]["action"] != rules[j]["action"]:
                if _rules_overlap(rules[i], rules[j]):
                    constraints.append((rules[i]["id"], rules[j]["id"]))

    # Minimal constraints via BFS reachability
    all_ids = set(r["id"] for r in rules)
    adj = {n: set() for n in all_ids}
    for a, b in constraints:
        adj[a].add(b)

    minimal = []
    for u, v in constraints:
        reachable = set()
        queue = []
        for w in adj[u]:
            if w != v and w not in reachable:
                reachable.add(w)
                queue.append(w)
        idx = 0
        while idx < len(queue):
            node = queue[idx]
            idx += 1
            for nb in adj[node]:
                if nb not in reachable:
                    reachable.add(nb)
                    queue.append(nb)
        if v not in reachable:
            minimal.append((u, v))

    return {
        "total_rules": len(rules),
        "unreachable_ids": unreachable,
        "constraint_count": len(constraints),
        "constraints": set(constraints),
        "minimal_count": len(minimal),
        "phase_boundaries": [15000, 30000],
    }


def test_correctness(packets, baseline_results):
    """Every packet must be classified identically to the baseline."""
    from optimized_classifier import AdaptiveClassifier

    classifier = AdaptiveClassifier(RULESET_PATH)
    for i, pkt in enumerate(packets):
        action, rule_id = classifier.classify(pkt)
        expected_action, expected_id = baseline_results[i]
        assert action == expected_action, (
            f"Packet {i}: expected action {expected_action}, got {action}"
        )
        assert rule_id == expected_id, (
            f"Packet {i}: expected rule_id {expected_id}, got {rule_id}"
        )


def test_unreachable_detection(ground_truth):
    """Detected unreachable rules must match ground truth."""
    from optimized_classifier import AdaptiveClassifier

    classifier = AdaptiveClassifier(RULESET_PATH)
    unreachable = classifier.get_unreachable_rules()
    assert unreachable == ground_truth["unreachable_ids"], (
        f"Unreachable mismatch: got {unreachable}, expected {ground_truth['unreachable_ids']}"
    )


def test_ordering_constraint_count(ground_truth):
    """Ordering constraint count must match expected."""
    from optimized_classifier import AdaptiveClassifier

    classifier = AdaptiveClassifier(RULESET_PATH)
    edges = classifier.get_ordering_constraints()
    assert len(edges) == ground_truth["constraint_count"], (
        f"Ordering constraint count: got {len(edges)}, "
        f"expected {ground_truth['constraint_count']}"
    )


def test_minimal_constraint_count(ground_truth):
    """Minimal constraint count must match expected."""
    from optimized_classifier import AdaptiveClassifier

    classifier = AdaptiveClassifier(RULESET_PATH)
    minimal = classifier.get_minimal_constraints()
    assert len(minimal) == ground_truth["minimal_count"], (
        f"Minimal constraint count: got {len(minimal)}, "
        f"expected {ground_truth['minimal_count']}"
    )


def test_phase_boundaries(ground_truth):
    """Phase boundary detection must be within +-500 of actual."""
    with open(ANALYSIS_PATH) as f:
        analysis = json.load(f)

    assert "phase_boundaries" in analysis, "Missing phase_boundaries in analysis"
    boundaries = analysis["phase_boundaries"]
    assert len(boundaries) == 2, f"Expected 2 phase boundaries, got {len(boundaries)}"

    expected_boundaries = ground_truth["phase_boundaries"]
    for actual, exp in zip(sorted(boundaries), sorted(expected_boundaries)):
        assert abs(actual - exp) <= 500, (
            f"Phase boundary {actual} too far from expected {exp} "
            f"(tolerance +-500)"
        )


def test_performance(packets):
    """Optimized classifier must achieve >= 5x speedup over baseline."""
    from optimized_classifier import AdaptiveClassifier

    baseline = BaselineClassifier(RULESET_PATH)
    optimized = AdaptiveClassifier(RULESET_PATH)

    start = time.perf_counter()
    for pkt in packets:
        baseline.classify(pkt)
    baseline_time = time.perf_counter() - start

    start = time.perf_counter()
    for pkt in packets:
        optimized.classify(pkt)
    opt_time = time.perf_counter() - start

    speedup = baseline_time / max(opt_time, 1e-9)
    assert speedup >= 5.0, (
        f"Speedup {speedup:.2f}x < 5x required "
        f"(baseline={baseline_time:.2f}s, optimized={opt_time:.2f}s)"
    )


def test_self_adjustment(packets):
    """Rule order must change during classification."""
    from optimized_classifier import AdaptiveClassifier

    classifier = AdaptiveClassifier(RULESET_PATH)
    initial_order = list(classifier.get_rule_order())

    for pkt in packets[:2000]:
        classifier.classify(pkt)

    new_order = list(classifier.get_rule_order())
    assert initial_order != new_order, "Rule order must change during classification"


def test_ordering_constraint_validity(packets, ground_truth):
    """Reordering must respect all ordering constraints at checkpoints."""
    from optimized_classifier import AdaptiveClassifier

    classifier = AdaptiveClassifier(RULESET_PATH)
    constraints = ground_truth["constraints"]
    checkpoints = [len(packets) // 4, len(packets) // 2, len(packets)]

    for idx, pkt in enumerate(packets):
        classifier.classify(pkt)
        if (idx + 1) in checkpoints:
            order = classifier.get_rule_order()
            pos = {rule_id: p for p, rule_id in enumerate(order)}
            for a, b in constraints:
                if a in pos and b in pos:
                    assert pos[a] < pos[b], (
                        f"Ordering constraint violation at packet {idx + 1}: "
                        f"rule {a} (pos {pos[a]}) must come before "
                        f"rule {b} (pos {pos[b]})"
                    )


def test_analysis_json(ground_truth):
    """Analysis JSON must exist with required structure and valid data."""
    with open(ANALYSIS_PATH) as f:
        analysis = json.load(f)

    assert analysis["total_rules"] == ground_truth["total_rules"], (
        f"total_rules: got {analysis['total_rules']}, "
        f"expected {ground_truth['total_rules']}"
    )

    assert "unreachable_rule_ids" in analysis, "Missing unreachable_rule_ids"
    assert analysis["unreachable_rule_ids"] == ground_truth["unreachable_ids"], (
        "unreachable_rule_ids mismatch"
    )

    assert "ordering_constraint_count" in analysis, "Missing ordering_constraint_count"
    assert analysis["ordering_constraint_count"] == ground_truth["constraint_count"]

    assert "minimal_constraint_count" in analysis, \
        "Missing minimal_constraint_count"
    assert analysis["minimal_constraint_count"] == \
        ground_truth["minimal_count"]

    assert "per_rule_hit_counts" in analysis, "Missing per_rule_hit_counts"
    hits = analysis["per_rule_hit_counts"]
    assert isinstance(hits, dict), "per_rule_hit_counts must be dict"
    assert len(hits) >= 20, (
        f"per_rule_hit_counts needs at least 20 entries, got {len(hits)}"
    )
    total_hit = sum(hits.values())
    assert total_hit > 0, "per_rule_hit_counts sum must be > 0"
