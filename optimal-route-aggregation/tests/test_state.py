"""Tests for the IPv4 FIB Manager with ORTC optimal route aggregation."""


import subprocess
import random
import time


def run_fib(commands):
    """Run the FIB manager with given commands and return output lines."""
    input_text = "\n".join(commands) + "\n"
    result = subprocess.run(
        ["/app/fib_manager"],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"fib_manager failed with code {result.returncode}: {result.stderr[:500]}"
    return [line for line in result.stdout.strip().split("\n") if line]


def ip_to_int(ip_str):
    a, b, c, d = ip_str.split(".")
    return (int(a) << 24) | (int(b) << 16) | (int(c) << 8) | int(d)


def int_to_ip(v):
    return f"{(v >> 24) & 0xFF}.{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


class ReferenceFIB:
    """Brute-force reference implementation for verification."""

    def __init__(self):
        self.routes = {}

    def insert(self, prefix_str, nexthop):
        ip_str, length = prefix_str.split("/")
        ip_int = ip_to_int(ip_str)
        pl = int(length)
        mask = (0xFFFFFFFF << (32 - pl)) & 0xFFFFFFFF if pl > 0 else 0
        self.routes[(ip_int & mask, pl)] = nexthop

    def delete(self, prefix_str):
        ip_str, length = prefix_str.split("/")
        ip_int = ip_to_int(ip_str)
        pl = int(length)
        mask = (0xFFFFFFFF << (32 - pl)) & 0xFFFFFFFF if pl > 0 else 0
        self.routes.pop((ip_int & mask, pl), None)

    def lookup(self, ip_str):
        ip_int = ip_to_int(ip_str)
        best_len = -1
        best_nh = None
        for (prefix_int, prefix_len), nh in self.routes.items():
            mask = (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF if prefix_len > 0 else 0
            if (ip_int & mask) == prefix_int and prefix_len > best_len:
                best_len = prefix_len
                best_nh = nh
        return best_nh

    def optimal_aggregate_count(self):
        """Compute optimal aggregated entry count using ORTC algorithm."""
        if not self.routes:
            return 0

        NONE = -1
        # Build trie: each node is [left, right, nexthop]
        T = [[NONE, NONE, NONE]]

        def nn():
            idx = len(T)
            T.append([NONE, NONE, NONE])
            return idx

        for (pi, pl), nh in self.routes.items():
            n = 0
            for i in range(pl):
                b = (pi >> (31 - i)) & 1
                c = T[n][b]
                if c == NONE:
                    c = nn()
                    T[n][b] = c
                n = c
            T[n][2] = nh

        # Phase 1: Normalize
        stack = [(0, NONE)]
        while stack:
            n, inh = stack.pop()
            eff = T[n][2] if T[n][2] != NONE else inh
            l, r = T[n][0], T[n][1]
            if l != NONE or r != NONE:
                if l == NONE:
                    l = nn()
                    T[l][2] = eff
                    T[n][0] = l
                if r == NONE:
                    r = nn()
                    T[r][2] = eff
                    T[n][1] = r
                stack.append((r, eff))
                stack.append((l, eff))

        # Phase 2: Bottom-up nh_sets
        _NONE_SET = frozenset([NONE])
        num = len(T)
        nh_sets = [None] * num
        pstack = [(0, False)]
        while pstack:
            n, done = pstack.pop()
            l, r = T[n][0], T[n][1]
            if l == NONE:
                nh_sets[n] = frozenset([T[n][2]])
                continue
            if done:
                if NONE in nh_sets[l] or NONE in nh_sets[r]:
                    nh_sets[n] = _NONE_SET
                else:
                    inter = nh_sets[l] & nh_sets[r]
                    nh_sets[n] = inter if inter else nh_sets[l] | nh_sets[r]
            else:
                pstack.append((n, True))
                pstack.append((r, False))
                pstack.append((l, False))

        # Phase 3: Count
        count = 0
        sstack = [(0, NONE)]
        while sstack:
            n, inh = sstack.pop()
            ns = nh_sets[n]
            if inh in ns:
                ch = inh
            else:
                ch = next(iter(ns))
                if ch != NONE:
                    count += 1
            l, r = T[n][0], T[n][1]
            if l != NONE:
                sstack.append((r, ch))
                sstack.append((l, ch))

        return count


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_basic_lookup():
    out = run_fib([
        "INSERT 10.0.0.0/8 1",
        "INSERT 172.16.0.0/12 2",
        "INSERT 192.168.0.0/16 3",
        "LOOKUP 10.1.2.3",
        "LOOKUP 172.16.5.1",
        "LOOKUP 192.168.1.1",
        "LOOKUP 8.8.8.8",
    ])
    assert out == ["1", "2", "3", "NONE"], f"Got: {out}"


def test_lpm():
    out = run_fib([
        "INSERT 10.0.0.0/8 1",
        "INSERT 10.0.0.0/16 2",
        "INSERT 10.0.0.0/24 3",
        "LOOKUP 10.0.0.1",
        "LOOKUP 10.0.1.1",
        "LOOKUP 10.1.0.1",
    ])
    assert out == ["3", "2", "1"], f"Got: {out}"


def test_insert_overwrite():
    out = run_fib([
        "INSERT 10.0.0.0/8 1",
        "LOOKUP 10.1.2.3",
        "INSERT 10.0.0.0/8 2",
        "LOOKUP 10.1.2.3",
    ])
    assert out == ["1", "2"], f"Got: {out}"


def test_insert_delete():
    out = run_fib([
        "INSERT 10.0.0.0/8 1",
        "LOOKUP 10.1.2.3",
        "DELETE 10.0.0.0/8",
        "LOOKUP 10.1.2.3",
        "INSERT 10.0.0.0/8 2",
        "LOOKUP 10.1.2.3",
    ])
    assert out == ["1", "NONE", "2"], f"Got: {out}"


def test_delete_fallback():
    out = run_fib([
        "INSERT 10.0.0.0/8 1",
        "INSERT 10.0.0.0/16 2",
        "LOOKUP 10.0.0.1",
        "DELETE 10.0.0.0/16",
        "LOOKUP 10.0.0.1",
    ])
    assert out == ["2", "1"], f"Got: {out}"


def test_delete_nonexistent():
    out = run_fib([
        "DELETE 10.0.0.0/8",
        "LOOKUP 10.1.2.3",
    ])
    assert out == ["NONE"], f"Got: {out}"


def test_default_route():
    out = run_fib([
        "INSERT 0.0.0.0/0 1",
        "INSERT 10.0.0.0/8 2",
        "LOOKUP 10.1.2.3",
        "LOOKUP 8.8.8.8",
        "LOOKUP 192.168.1.1",
    ])
    assert out == ["2", "1", "1"], f"Got: {out}"


def test_host_route():
    out = run_fib([
        "INSERT 10.0.0.1/32 5",
        "LOOKUP 10.0.0.1",
        "LOOKUP 10.0.0.2",
        "INSERT 0.0.0.0/0 3",
        "LOOKUP 10.0.0.2",
        "LOOKUP 10.0.0.1",
    ])
    assert out == ["5", "NONE", "3", "5"], f"Got: {out}"


def test_aggregation_simple():
    """Two adjacent /24s with same nexthop -> one /23."""
    out = run_fib([
        "INSERT 10.0.0.0/24 1",
        "INSERT 10.0.1.0/24 1",
        "AGGREGATE",
    ])
    count = int(out[0])
    assert count == 1, f"Expected 1 entry, got {count}. Full output: {out}"
    assert out[1] == "10.0.0.0/23 1", f"Expected '10.0.0.0/23 1', got '{out[1]}'"


def test_aggregation_ortc():
    """
    Requires ORTC — greedy merge produces 3 entries, optimal is 2.

    Routes: 10.0.0.0/24->1, 10.0.1.0/24->1, 10.0.0.0/25->2

    Greedy cannot merge the two /24s (left /24 has a /25 override),
    producing: /24->1, /25->2, /24->1 = 3 entries.

    ORTC promotes nexthop 1 to /23, keeping only the /25 exception = 2 entries.
    """
    out = run_fib([
        "INSERT 10.0.0.0/24 1",
        "INSERT 10.0.1.0/24 1",
        "INSERT 10.0.0.0/25 2",
        "AGGREGATE",
    ])
    count = int(out[0])
    assert count == 2, (
        f"Expected 2 entries (ORTC optimal), got {count}. "
        f"If you got 3, your aggregation is greedy, not optimal. Output: {out}"
    )

    # Verify forwarding behavior of the aggregated table
    ref = ReferenceFIB()
    ref.insert("10.0.0.0/24", 1)
    ref.insert("10.0.1.0/24", 1)
    ref.insert("10.0.0.0/25", 2)

    agg = ReferenceFIB()
    for line in out[1:]:
        parts = line.split()
        agg.insert(parts[0], int(parts[1]))

    for ip in ["10.0.0.1", "10.0.0.127", "10.0.0.128", "10.0.0.255",
               "10.0.1.1", "10.0.1.255", "8.8.8.8"]:
        assert ref.lookup(ip) == agg.lookup(ip), (
            f"Forwarding mismatch at {ip}: ref={ref.lookup(ip)}, agg={agg.lookup(ip)}"
        )


def test_aggregation_alternating():
    """
    Alternating nexthops: 192.168.{0,1,2,3}.0/24 -> {1,2,1,2}.

    Greedy: 4 entries (no adjacent pair has same nexthop).
    ORTC: 3 entries (promote one nexthop to /22, add 2 exceptions).
    """
    out = run_fib([
        "INSERT 192.168.0.0/24 1",
        "INSERT 192.168.1.0/24 2",
        "INSERT 192.168.2.0/24 1",
        "INSERT 192.168.3.0/24 2",
        "AGGREGATE",
    ])
    count = int(out[0])
    assert count == 3, (
        f"Expected 3 entries (ORTC optimal), got {count}. "
        f"If you got 4, your aggregation is greedy. Output: {out}"
    )

    ref = ReferenceFIB()
    ref.insert("192.168.0.0/24", 1)
    ref.insert("192.168.1.0/24", 2)
    ref.insert("192.168.2.0/24", 1)
    ref.insert("192.168.3.0/24", 2)

    agg = ReferenceFIB()
    for line in out[1:]:
        parts = line.split()
        agg.insert(parts[0], int(parts[1]))

    for ip in ["192.168.0.1", "192.168.1.1", "192.168.2.1",
               "192.168.3.1", "192.168.4.1", "8.8.8.8"]:
        assert ref.lookup(ip) == agg.lookup(ip), (
            f"Forwarding mismatch at {ip}: ref={ref.lookup(ip)}, agg={agg.lookup(ip)}"
        )


def test_aggregation_with_default():
    """Aggregation with a /0 default route."""
    out = run_fib([
        "INSERT 0.0.0.0/0 1",
        "INSERT 10.0.0.0/8 2",
        "INSERT 10.0.0.0/16 1",
        "AGGREGATE",
    ])
    count = int(out[0])
    # 0/0->1, /8->2, /16->1 are all needed: removing any changes behavior
    assert count == 3, f"Expected 3 entries, got {count}. Output: {out}"

    ref = ReferenceFIB()
    ref.insert("0.0.0.0/0", 1)
    ref.insert("10.0.0.0/8", 2)
    ref.insert("10.0.0.0/16", 1)

    agg = ReferenceFIB()
    for line in out[1:]:
        parts = line.split()
        agg.insert(parts[0], int(parts[1]))

    for ip in ["10.0.0.1", "10.0.1.1", "10.1.0.1", "8.8.8.8",
               "192.168.1.1", "0.0.0.1"]:
        assert ref.lookup(ip) == agg.lookup(ip), (
            f"Forwarding mismatch at {ip}: ref={ref.lookup(ip)}, agg={agg.lookup(ip)}"
        )


def test_aggregation_empty():
    """Aggregation of empty table."""
    out = run_fib(["AGGREGATE"])
    assert out == ["0"], f"Expected ['0'], got {out}"


def test_aggregate_nondestructive():
    """AGGREGATE must not modify the internal routing table."""
    out = run_fib([
        "INSERT 10.0.0.0/24 1",
        "INSERT 10.0.1.0/24 1",
        "AGGREGATE",
        "LOOKUP 10.0.0.1",
        "LOOKUP 10.0.1.1",
        "INSERT 10.0.2.0/24 2",
        "LOOKUP 10.0.2.1",
    ])
    # AGGREGATE output: "1\n10.0.0.0/23 1"
    # Then LOOKUP outputs
    assert out[-3] == "1", f"LOOKUP after AGGREGATE failed: {out}"
    assert out[-2] == "1", f"LOOKUP after AGGREGATE failed: {out}"
    assert out[-1] == "2", f"INSERT after AGGREGATE failed: {out}"


def test_large_scale_aggregation():
    """
    Generate a routing table with many entries and verify optimal aggregation
    count matches reference ORTC and forwarding behavior is preserved.
    """
    random.seed(42)

    ref = ReferenceFIB()
    commands = []

    generated = set()
    for _ in range(2000):
        plen = random.randint(8, 28)
        ip_int = random.randint(0, 0xFFFFFFFF)
        mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
        prefix_int = ip_int & mask
        if (prefix_int, plen) in generated:
            continue
        generated.add((prefix_int, plen))
        nh = random.randint(1, 10)
        prefix_str = f"{int_to_ip(prefix_int)}/{plen}"
        commands.append(f"INSERT {prefix_str} {nh}")
        ref.insert(prefix_str, nh)

    commands.append("AGGREGATE")

    out = run_fib(commands)
    count = int(out[0])

    # Compute optimal count using reference ORTC
    optimal = ref.optimal_aggregate_count()
    assert count == optimal, (
        f"Aggregation not optimal: got {count} entries, expected {optimal}"
    )

    # Verify forwarding behavior on random probe IPs
    entries = out[1:]
    assert len(entries) == count, (
        f"Count header says {count}, but got {len(entries)} entries"
    )

    agg = ReferenceFIB()
    for line in entries:
        parts = line.split()
        agg.insert(parts[0], int(parts[1]))

    for _ in range(5000):
        ip_int = random.randint(0, 0xFFFFFFFF)
        ip_str = int_to_ip(ip_int)
        ref_result = ref.lookup(ip_str)
        agg_result = agg.lookup(ip_str)
        assert ref_result == agg_result, (
            f"Forwarding mismatch at {ip_str}: ref={ref_result}, agg={agg_result}"
        )


def test_performance():
    """Test that lookups complete within the time limit."""
    random.seed(123)
    commands = []

    generated = set()
    for _ in range(10000):
        plen = random.randint(8, 28)
        ip_int = random.randint(0, 0xFFFFFFFF)
        mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
        prefix_int = ip_int & mask
        if (prefix_int, plen) in generated:
            continue
        generated.add((prefix_int, plen))
        nh = random.randint(1, 50)
        commands.append(f"INSERT {int_to_ip(prefix_int)}/{plen} {nh}")

    for _ in range(200000):
        ip_int = random.randint(0, 0xFFFFFFFF)
        commands.append(f"LOOKUP {int_to_ip(ip_int)}")

    start = time.time()
    out = run_fib(commands)
    elapsed = time.time() - start

    assert elapsed < 60, f"Too slow: {elapsed:.1f}s (limit: 60s)"

    num_lookups = sum(1 for c in commands if c.startswith("LOOKUP"))
    assert len(out) == num_lookups, (
        f"Expected {num_lookups} outputs, got {len(out)}"
    )
