
import json
import os
import subprocess
import pytest


RESULTS_DIR = "/app/results"
ANALYZER = "/app/analyzer.py"


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the analyzer once before all tests."""
    assert os.path.isfile(ANALYZER), f"Analyzer not found at {ANALYZER}"
    result = subprocess.run(
        ["python3", ANALYZER],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Analyzer failed with exit code {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def load_result(scenario_name):
    path = os.path.join(RESULTS_DIR, scenario_name)
    assert os.path.isfile(path), f"Result file not found: {path}"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Scenario 1: basic_flow
# 10 unique packets, conntrack_max=20, no overflow
# ---------------------------------------------------------------------------
class TestBasicFlow:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = load_result("basic_flow.json")

    def test_raw_counter(self):
        assert self.result["counters"]["raw_PREROUTING"] == 10

    def test_mangle_counter(self):
        assert self.result["counters"]["mangle_PREROUTING"] == 10

    def test_filter_counter(self):
        assert self.result["counters"]["filter_INPUT"] == 10

    def test_conntrack_entries(self):
        assert self.result["conntrack_entries"] == 10

    def test_conntrack_drops(self):
        assert self.result["conntrack_drops"] == 0

    def test_verdicts(self):
        assert self.result["verdicts"] == ["ACCEPT"] * 10


# ---------------------------------------------------------------------------
# Scenario 2: conntrack_overflow
# 10 unique packets, conntrack_max=7, overflow at 8th packet
# ---------------------------------------------------------------------------
class TestConntrackOverflow:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = load_result("conntrack_overflow.json")

    def test_raw_counter(self):
        assert self.result["counters"]["raw_PREROUTING"] == 10

    def test_mangle_counter(self):
        assert self.result["counters"]["mangle_PREROUTING"] == 7

    def test_filter_counter(self):
        assert self.result["counters"]["filter_INPUT"] == 7

    def test_conntrack_entries(self):
        assert self.result["conntrack_entries"] == 7

    def test_conntrack_drops(self):
        assert self.result["conntrack_drops"] == 3

    def test_verdicts(self):
        expected = ["ACCEPT"] * 7 + ["CT_DROP"] * 3
        assert self.result["verdicts"] == expected

    def test_mangle_raw_difference_equals_drops(self):
        """The gap between raw and mangle counters equals conntrack drops."""
        raw = self.result["counters"]["raw_PREROUTING"]
        mangle = self.result["counters"]["mangle_PREROUTING"]
        assert raw - mangle == self.result["conntrack_drops"]


# ---------------------------------------------------------------------------
# Scenario 3: notrack_bypass
# 5 tracked to port 80 (fill table), 5 NOTRACK to port 443 (bypass),
# 5 more tracked to port 80 (all CT_DROP)
# ---------------------------------------------------------------------------
class TestNotrackBypass:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = load_result("notrack_bypass.json")

    def test_raw_counter(self):
        assert self.result["counters"]["raw_PREROUTING"] == 15

    def test_mangle_counter(self):
        assert self.result["counters"]["mangle_PREROUTING"] == 10

    def test_filter_counter(self):
        assert self.result["counters"]["filter_INPUT"] == 10

    def test_conntrack_entries(self):
        assert self.result["conntrack_entries"] == 5

    def test_conntrack_drops(self):
        assert self.result["conntrack_drops"] == 5

    def test_verdicts(self):
        expected = (
            ["ACCEPT"] * 5    # tracked to port 80 - fill table
            + ["ACCEPT"] * 5  # NOTRACK to port 443 - bypass
            + ["CT_DROP"] * 5 # tracked to port 80 - table full
        )
        assert self.result["verdicts"] == expected

    def test_notrack_packets_bypass_conntrack(self):
        """NOTRACK packets must not consume conntrack table entries."""
        assert self.result["conntrack_entries"] == 5  # only port-80 flows


# ---------------------------------------------------------------------------
# Scenario 4: drop_no_confirm
# 10 packets to port 80, filter DROP on port 80, conntrack_max=3
# Dropped packets don't confirm conntrack entries, so table never fills
# ---------------------------------------------------------------------------
class TestDropNoConfirm:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = load_result("drop_no_confirm.json")

    def test_raw_counter(self):
        assert self.result["counters"]["raw_PREROUTING"] == 10

    def test_mangle_counter(self):
        """All packets reach mangle because DROP removes entries before next packet."""
        assert self.result["counters"]["mangle_PREROUTING"] == 10

    def test_filter_counter(self):
        assert self.result["counters"]["filter_INPUT"] == 10

    def test_conntrack_entries(self):
        """No confirmed entries because all packets were DROPped."""
        assert self.result["conntrack_entries"] == 0

    def test_conntrack_drops(self):
        """No conntrack drops because entries are freed after each DROP."""
        assert self.result["conntrack_drops"] == 0

    def test_verdicts(self):
        assert self.result["verdicts"] == ["DROP"] * 10

    def test_table_never_fills(self):
        """Even with conntrack_max=3, table never fills because entries
        are removed when packets are DROPped in filter."""
        raw = self.result["counters"]["raw_PREROUTING"]
        mangle = self.result["counters"]["mangle_PREROUTING"]
        assert raw == mangle  # no gap means no conntrack drops


# ---------------------------------------------------------------------------
# Scenario 5: mixed_complex
# Mixed traffic: tracked ACCEPT, tracked DROP, NOTRACK, more tracked
# conntrack_max=8
# ---------------------------------------------------------------------------
class TestMixedComplex:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = load_result("mixed_complex.json")

    def test_raw_counter(self):
        assert self.result["counters"]["raw_PREROUTING"] == 16

    def test_mangle_counter(self):
        assert self.result["counters"]["mangle_PREROUTING"] == 14

    def test_filter_counter(self):
        assert self.result["counters"]["filter_INPUT"] == 14

    def test_conntrack_entries(self):
        # 5 from first batch (port 80 ACCEPT) + 3 from last batch (port 80 ACCEPT)
        # port 22 entries removed on DROP, port 443 is NOTRACK
        assert self.result["conntrack_entries"] == 8

    def test_conntrack_drops(self):
        assert self.result["conntrack_drops"] == 2

    def test_verdicts(self):
        expected = (
            ["ACCEPT"] * 5     # port 80 batch 1
            + ["DROP"] * 3     # port 22 (DROP in filter)
            + ["ACCEPT"] * 3   # port 443 (NOTRACK, ACCEPT)
            + ["ACCEPT"] * 3   # port 80 batch 2 (table 5->8)
            + ["CT_DROP"] * 2  # port 80 batch 2 overflow
        )
        assert self.result["verdicts"] == expected

    def test_drop_entries_removed(self):
        """Port-22 packets were DROPped, so their conntrack entries were
        removed. This kept the table at 5 instead of 8 after phase 2."""
        # If DROP didn't remove entries, table would be at 8 after phase 2,
        # and all 5 phase-4 packets would be CT_DROPped (instead of just 2)
        assert self.result["conntrack_drops"] == 2  # not 5


# ---------------------------------------------------------------------------
# Scenario 6: duplicate_flows
# 5 unique flows fill table, 5 duplicate flows (existing entries), 3 new flows CT_DROP
# ---------------------------------------------------------------------------
class TestDuplicateFlows:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = load_result("duplicate_flows.json")

    def test_raw_counter(self):
        assert self.result["counters"]["raw_PREROUTING"] == 13

    def test_mangle_counter(self):
        assert self.result["counters"]["mangle_PREROUTING"] == 10

    def test_filter_counter(self):
        assert self.result["counters"]["filter_INPUT"] == 10

    def test_conntrack_entries(self):
        assert self.result["conntrack_entries"] == 5

    def test_conntrack_drops(self):
        assert self.result["conntrack_drops"] == 3

    def test_verdicts(self):
        expected = (
            ["ACCEPT"] * 5   # 5 unique flows fill table
            + ["ACCEPT"] * 5 # 5 duplicates - existing flows, no new entries
            + ["CT_DROP"] * 3 # 3 new flows - table full
        )
        assert self.result["verdicts"] == expected

    def test_duplicates_dont_consume_capacity(self):
        """Packets matching existing flows must not be CT_DROPped even
        when the table is at max capacity."""
        verdicts = self.result["verdicts"]
        # Verdicts 5-9 (duplicate packets) should all be ACCEPT
        assert verdicts[5:10] == ["ACCEPT"] * 5
