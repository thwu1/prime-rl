import json
import os
import re
import pytest


REPORT_PATH = "/app/timing_report.json"
OPTIMIZED_NETLIST = "/app/optimized_netlist.v"

# Expected values for the provided ripple-carry netlist
# Cell counts from direct netlist analysis
EXPECTED_TOTAL_CELLS = 30
EXPECTED_CELL_COUNTS = {
    "DFFR_X1": 13,
    "XOR2_X1": 7,
    "AND2_X1": 7,
    "OR2_X1": 3,
}
# Area = 13*3.990 + 7*1.596 + 7*1.064 + 3*1.064 = 73.682
EXPECTED_AREA = 73.682
CLOCK_PERIOD = 0.250


def load_report():
    with open(REPORT_PATH, "r") as f:
        return json.load(f)


# ── Structure tests ──────────────────────────────────────────────────

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), f"{REPORT_PATH} not found"

    def test_report_is_valid_json(self):
        report = load_report()
        assert isinstance(report, dict), "Report must be a JSON object"

    def test_has_original_section(self):
        report = load_report()
        assert "original" in report, "Report must contain 'original' section"

    def test_has_optimized_section(self):
        report = load_report()
        assert "optimized" in report, "Report must contain 'optimized' section"

    def test_has_simulation_verified(self):
        report = load_report()
        assert "simulation_verified" in report, "Report must contain 'simulation_verified'"

    def test_has_max_frequency(self):
        report = load_report()
        assert "max_frequency_mhz" in report, "Report must contain 'max_frequency_mhz'"

    def test_original_has_required_fields(self):
        report = load_report()
        orig = report["original"]
        required = [
            "total_cells", "total_area_um2", "critical_path_delay_ns",
            "setup_time_ns", "clock_period_ns", "worst_slack_ns", "meets_timing"
        ]
        for field in required:
            assert field in orig, f"original.{field} missing"

    def test_optimized_has_required_fields(self):
        report = load_report()
        opt = report["optimized"]
        required = [
            "total_cells", "total_area_um2", "critical_path_delay_ns",
            "meets_timing", "worst_slack_ns"
        ]
        for field in required:
            assert field in opt, f"optimized.{field} missing"


# ── Original netlist cell metrics ────────────────────────────────────

class TestOriginalCellMetrics:
    def test_total_cells(self):
        """Exact cell count from the provided netlist."""
        report = load_report()
        total = report["original"]["total_cells"]
        assert total == EXPECTED_TOTAL_CELLS, (
            f"Expected {EXPECTED_TOTAL_CELLS} cells, got {total}"
        )

    def test_cell_counts_if_provided(self):
        """If cell_counts is provided, verify key types."""
        report = load_report()
        orig = report["original"]
        counts = orig.get("cell_counts", {})
        if counts:
            for cell_type, expected_n in EXPECTED_CELL_COUNTS.items():
                actual = counts.get(cell_type, 0)
                assert actual == expected_n, (
                    f"{cell_type}: expected {expected_n}, got {actual}"
                )

    def test_total_area(self):
        """Area must match Liberty data within tolerance."""
        report = load_report()
        area = report["original"]["total_area_um2"]
        assert abs(area - EXPECTED_AREA) < 2.0, (
            f"Expected area ~{EXPECTED_AREA}, got {area}"
        )


# ── STA results for original netlist ─────────────────────────────────

class TestOriginalSTA:
    def test_critical_path_delay_range(self):
        """Critical path delay must be physically plausible for 45nm 4-bit adder."""
        report = load_report()
        delay = report["original"]["critical_path_delay_ns"]
        assert 0.15 < delay < 0.50, (
            f"Critical path delay {delay} ns is outside plausible range [0.15, 0.50]"
        )

    def test_setup_time_range(self):
        """Setup time must be physically plausible."""
        report = load_report()
        setup = report["original"]["setup_time_ns"]
        assert 0.010 < setup < 0.080, (
            f"Setup time {setup} ns is outside plausible range"
        )

    def test_clock_period(self):
        """Clock period must match SDC constraint."""
        report = load_report()
        period = report["original"]["clock_period_ns"]
        assert abs(period - CLOCK_PERIOD) < 0.001, (
            f"Clock period should be {CLOCK_PERIOD}, got {period}"
        )

    def test_timing_fails(self):
        """Design must fail timing at 0.250 ns with ripple carry."""
        report = load_report()
        assert report["original"]["meets_timing"] is False, (
            "Ripple carry adder should NOT meet timing at 4 GHz"
        )

    def test_slack_is_negative(self):
        """Worst slack must be negative (timing violation)."""
        report = load_report()
        slack = report["original"]["worst_slack_ns"]
        assert slack < 0, f"Slack should be negative, got {slack}"

    def test_slack_consistency(self):
        """Verify slack = clock_period - (delay + setup)."""
        report = load_report()
        orig = report["original"]
        delay = orig["critical_path_delay_ns"]
        setup = orig["setup_time_ns"]
        period = orig["clock_period_ns"]
        slack = orig["worst_slack_ns"]
        expected_slack = period - delay - setup
        assert abs(slack - expected_slack) < 0.005, (
            f"Slack {slack} inconsistent: period({period}) - delay({delay}) "
            f"- setup({setup}) = {expected_slack}"
        )

    def test_critical_path_has_carry_chain(self):
        """Critical path must traverse the carry chain (AND+OR pattern)."""
        report = load_report()
        orig = report["original"]
        stages = orig.get("critical_path_stages", [])
        if not stages:
            pytest.skip("critical_path_stages not provided")
        cell_types = [s.get("cell", s.get("cell_type", "")) for s in stages]
        type_str = " ".join(cell_types)
        # Must contain AND and OR gates in carry chain pattern
        has_and = any("AND" in c for c in cell_types)
        has_or = any("OR" in c for c in cell_types)
        has_dff = any("DFF" in c for c in cell_types)
        assert has_and and has_or, (
            f"Critical path should contain AND and OR gates (carry chain). "
            f"Got: {type_str}"
        )

    def test_critical_path_min_stages(self):
        """Critical path through 4-bit ripple carry should have >= 6 stages."""
        report = load_report()
        stages = report["original"].get("critical_path_stages", [])
        if not stages:
            pytest.skip("critical_path_stages not provided")
        assert len(stages) >= 6, (
            f"Expected >= 6 stages in critical path, got {len(stages)}"
        )


# ── Optimized netlist tests ──────────────────────────────────────────

class TestOptimized:
    def test_optimized_netlist_exists(self):
        """Optimized netlist file must exist."""
        assert os.path.exists(OPTIMIZED_NETLIST), (
            f"{OPTIMIZED_NETLIST} not found"
        )

    def test_optimized_netlist_is_verilog(self):
        """Optimized netlist must be valid Verilog (contains module keyword)."""
        with open(OPTIMIZED_NETLIST, "r") as f:
            content = f.read()
        assert "module" in content.lower(), (
            "Optimized netlist does not appear to be valid Verilog"
        )

    def test_optimized_delay_less_than_original(self):
        """Optimization must reduce critical path delay."""
        report = load_report()
        orig_delay = report["original"]["critical_path_delay_ns"]
        opt_delay = report["optimized"]["critical_path_delay_ns"]
        assert opt_delay < orig_delay, (
            f"Optimized delay {opt_delay} should be less than original {orig_delay}"
        )

    def test_optimized_has_positive_metrics(self):
        """Optimized metrics must be positive."""
        report = load_report()
        opt = report["optimized"]
        assert opt["total_cells"] > 0, "Optimized total_cells must be > 0"
        assert opt["total_area_um2"] > 0, "Optimized area must be > 0"
        assert opt["critical_path_delay_ns"] > 0, "Optimized delay must be > 0"


# ── Simulation verification ──────────────────────────────────────────

class TestSimulation:
    def test_simulation_passed(self):
        """Solver must have verified netlists via simulation."""
        report = load_report()
        assert report["simulation_verified"] is True, (
            "simulation_verified must be true"
        )


# ── Max frequency ────────────────────────────────────────────────────

class TestFrequency:
    def test_max_frequency_positive(self):
        report = load_report()
        freq = report["max_frequency_mhz"]
        assert freq > 0, "max_frequency_mhz must be positive"

    def test_max_frequency_plausible(self):
        """Max frequency should be in plausible range for 45nm."""
        report = load_report()
        freq = report["max_frequency_mhz"]
        assert 500 < freq < 10000, (
            f"Max frequency {freq} MHz outside plausible range for 45nm"
        )

    def test_max_frequency_consistency(self):
        """Max frequency should be consistent with critical path delay."""
        report = load_report()
        orig = report["original"]
        delay = orig["critical_path_delay_ns"]
        setup = orig["setup_time_ns"]
        freq = report["max_frequency_mhz"]
        expected_freq = 1000.0 / (delay + setup)
        # Allow 20% tolerance for different computation methods
        ratio = freq / expected_freq
        assert 0.7 < ratio < 1.4, (
            f"max_frequency {freq} MHz inconsistent with delay {delay} + "
            f"setup {setup} -> expected ~{expected_freq:.1f} MHz"
        )
