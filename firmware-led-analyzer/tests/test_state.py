
import json
import math
import os
import sys

import pytest

sys.path.insert(0, "/app")
from corrected import CProcessor, RustProcessor, analyze_divergences


# ---------------------------------------------------------------------------
# C wave table correctness
# ---------------------------------------------------------------------------
class TestCWaveTable:
    def test_length(self):
        assert len(CProcessor().get_wave_table()) == 51

    def test_boundary_values(self):
        table = CProcessor().get_wave_table()
        assert table[0] == 0
        assert table[25] == 255
        assert table[50] == 0

    def test_symmetry(self):
        table = CProcessor().get_wave_table()
        n = len(table)
        for i in range(n):
            assert table[i] == table[n - 1 - i]


# ---------------------------------------------------------------------------
# C hue normalization — requires understanding C's > vs >= semantics
# ---------------------------------------------------------------------------
class TestCHueNormalization:
    def test_zero_hue_maps_to_360(self):
        """C: (h > 0 ? h : 360 + h) — 0.0 > 0 is false, so h=0 → 360."""
        h, _, _ = CProcessor().normalize_color(0.0, 1.0, 1.0)
        assert h == 360

    def test_negative_hue(self):
        h, _, _ = CProcessor().normalize_color(-30.0, 1.0, 1.0)
        assert h == 330

    def test_positive_hue_passthrough(self):
        h, s, v = CProcessor().normalize_color(120.0, 1.0, 0.8)
        assert (h, s, v) == (120, 255, 204)

    def test_large_positive_hue_no_modulo(self):
        """C does NOT apply modulo to positive hue values."""
        h, _, _ = CProcessor().normalize_color(720.0, 1.0, 1.0)
        assert h == 720


# ---------------------------------------------------------------------------
# C wave cycle timing — hardcoded constant vs array length
# ---------------------------------------------------------------------------
class TestCWaveCycleTiming:
    def test_dc50_pause(self):
        t = CProcessor().compute_wave_cycle_timing(50)
        assert t["tick_ms"] == 20
        assert t["num_entries"] == 51
        assert t["pause_ms"] == 2000

    def test_dc30_pause(self):
        t = CProcessor().compute_wave_cycle_timing(30)
        assert t["pause_ms"] == 3333

    def test_dc100_pause(self):
        t = CProcessor().compute_wave_cycle_timing(100)
        assert t["pause_ms"] == 1000


# ---------------------------------------------------------------------------
# C blink timing
# ---------------------------------------------------------------------------
class TestCBlinkTiming:
    def test_50pct(self):
        assert CProcessor().compute_blink_timing(200, 50) == (100, 100)

    def test_10pct(self):
        assert CProcessor().compute_blink_timing(1000, 10) == (100, 900)


# ---------------------------------------------------------------------------
# Rust HSV-to-RGB — truncation semantics
# ---------------------------------------------------------------------------
class TestRustHsvToRgb:
    @pytest.mark.parametrize(
        "h, s, v, expected",
        [
            (0.0, 1.0, 1.0, (255, 0, 0)),
            (60.0, 1.0, 1.0, (255, 255, 0)),
            (120.0, 1.0, 1.0, (0, 255, 0)),
            (180.0, 1.0, 1.0, (0, 255, 255)),
            (240.0, 1.0, 1.0, (0, 0, 255)),
            (300.0, 1.0, 1.0, (255, 0, 255)),
        ],
    )
    def test_primary_and_secondary(self, h, s, v, expected):
        assert RustProcessor().hsv_to_rgb(h, s, v) == expected

    def test_truncation_not_rounding(self):
        """Rust 'as u8' truncates: 127.5 → 127, not 128."""
        assert RustProcessor().hsv_to_rgb(0.0, 0.5, 1.0) == (255, 127, 127)

    def test_negative_hue_truncation(self):
        """h=-30 → sector 300..360: b = 0.5*255 = 127.5 → 127."""
        assert RustProcessor().hsv_to_rgb(-30.0, 1.0, 1.0) == (255, 0, 127)

    def test_large_hue_wraps(self):
        assert RustProcessor().hsv_to_rgb(480.0, 1.0, 1.0) == (0, 255, 0)

    def test_zero_saturation(self):
        assert RustProcessor().hsv_to_rgb(0.0, 0.0, 1.0) == (255, 255, 255)


# ---------------------------------------------------------------------------
# Rust wave table — cosine formula and last-entry duration
# ---------------------------------------------------------------------------
class TestRustWaveTable:
    def test_length(self):
        assert len(RustProcessor().compute_wave_table(3000)) == 70

    def test_cosine_formula_all_entries(self):
        """Every entry (except last) must match the exact Rust cosine formula."""
        table = RustProcessor().compute_wave_table(3000)
        N = 70
        for i in range(N - 1):
            expected = int(
                math.trunc(
                    255.0
                    / 2.0
                    * (1.0 + math.cos(math.pi * (2.0 * i - N) / N))
                )
            )
            assert table[i][0] == expected, f"index {i}: got {table[i][0]}, want {expected}"

    def test_peak_at_midpoint(self):
        """At index 35, cosine arg is 0 → brightness = 255."""
        assert RustProcessor().compute_wave_table(3000)[35][0] == 255

    def test_last_entry_brightness_zero(self):
        assert RustProcessor().compute_wave_table(3000)[69][0] == 0

    def test_last_entry_duration(self):
        """duration = period - (N * tick) = 3000 - 2100 = 900."""
        assert RustProcessor().compute_wave_table(3000)[69][1] == 900

    def test_regular_tick_duration(self):
        table = RustProcessor().compute_wave_table(3000)
        for i in range(69):
            assert table[i][1] == 30

    def test_different_period(self):
        """Verify last-entry duration scales with period."""
        table = RustProcessor().compute_wave_table(5000)
        assert table[69][1] == 5000 - (70 * 30)


# ---------------------------------------------------------------------------
# Rust blink timing — subtraction vs independent division
# ---------------------------------------------------------------------------
class TestRustBlinkTiming:
    def test_standard_50pct(self):
        assert RustProcessor().compute_blink_timing(200, 50) == (100, 100)

    def test_subtraction_guarantees_sum(self):
        """Rust: off = period - on. For period=7, dc=33: on=2, off=5 (sum=7)."""
        on, off = RustProcessor().compute_blink_timing(7, 33)
        assert on == 2
        assert off == 5
        assert on + off == 7

    def test_another_asymmetric(self):
        """period=13, dc=40: on=5, off=8 (sum=13)."""
        on, off = RustProcessor().compute_blink_timing(13, 40)
        assert on == 5
        assert off == 8


# ---------------------------------------------------------------------------
# Command parsing (both processors)
# ---------------------------------------------------------------------------
class TestCommandParsing:
    def test_c_blink(self):
        cmd = CProcessor().parse_command(
            json.dumps({
                "pattern": {"type": "blink", "details": {
                    "duration_ms": 1000, "period_ms": 200, "dc": 0.5,
                    "color": {"h": 120.0, "s": 1.0, "v": 0.8},
                }}
            })
        )
        assert cmd["pattern"] == "blink"
        assert cmd["color"] == (120, 255, 204)

    def test_c_no_dc_validation(self):
        """C does NOT reject dc > 1.0."""
        cmd = CProcessor().parse_command(
            json.dumps({
                "pattern": {"type": "blink", "details": {
                    "duration_ms": 1000, "period_ms": 200, "dc": 1.5,
                    "color": {"h": 120.0, "s": 1.0, "v": 1.0},
                }}
            })
        )
        assert cmd is not None
        assert cmd["duty_cycle"] == 150

    def test_rust_dc_validation(self):
        """Rust rejects dc > 1.0."""
        cmd = RustProcessor().parse_command(
            json.dumps({
                "pattern": {"type": "blink", "details": {
                    "duration_ms": 1000, "period_ms": 200, "dc": 1.5,
                    "color": {"h": 120.0, "s": 1.0, "v": 1.0},
                }}
            })
        )
        assert cmd is None

    def test_rust_wave_period_validation(self):
        """Rust rejects wave period < MIN_WAVE_PERIOD_MS (2100)."""
        cmd = RustProcessor().parse_command(
            json.dumps({
                "pattern": {"type": "wave", "details": {
                    "duration_ms": 5000, "period_ms": 1000, "dc": 0.5,
                    "color": {"h": 120.0, "s": 1.0, "v": 1.0},
                }}
            })
        )
        assert cmd is None

    def test_invalid_json(self):
        assert CProcessor().parse_command("not json{") is None
        assert RustProcessor().parse_command("not json{") is None

    def test_off_pattern(self):
        for proc_cls in (CProcessor, RustProcessor):
            cmd = proc_cls().parse_command(json.dumps({"pattern": {"type": "off"}}))
            assert cmd["pattern"] == "off"


# ---------------------------------------------------------------------------
# Divergence analysis
# ---------------------------------------------------------------------------
class TestDivergenceAnalysis:
    @pytest.fixture()
    def report(self):
        return analyze_divergences(
            json.dumps({
                "pattern": {"type": "wave", "details": {
                    "duration_ms": 5000, "period_ms": 3000, "dc": 0.5,
                    "color": {"h": 120.0, "s": 1.0, "v": 1.0},
                }}
            })
        )

    def test_wave_table_lengths(self, report):
        assert report["wave_table"]["c_length"] == 51
        assert report["wave_table"]["rust_length"] == 70

    def test_color_model(self, report):
        assert "hsv" in report["color_model"]["c_model"].lower()
        assert "rgb" in report["color_model"]["rust_model"].lower()

    def test_wave_tick_period(self, report):
        assert report["wave_tick_period"]["c_ms"] == 20
        assert report["wave_tick_period"]["rust_ms"] == 30

    def test_duty_cycle_validation(self, report):
        assert report["duty_cycle_validation"]["c_validates"] is False
        assert report["duty_cycle_validation"]["rust_validates"] is True

    def test_min_categories(self, report):
        assert len(report) >= 5


# ---------------------------------------------------------------------------
# Audit report structure
# ---------------------------------------------------------------------------
class TestAuditReport:
    @pytest.fixture()
    def bugs(self):
        path = "/app/audit_report.json"
        assert os.path.isfile(path), "audit_report.json not found"
        with open(path) as f:
            data = json.load(f)
        return data

    def test_is_list(self, bugs):
        assert isinstance(bugs, list)

    def test_minimum_bug_count(self, bugs):
        assert len(bugs) >= 6, f"Expected >= 6 bugs, found {len(bugs)}"

    def test_required_keys(self, bugs):
        required = {"bug_id", "location", "description", "impact"}
        for i, bug in enumerate(bugs):
            missing = required - set(bug.keys())
            assert not missing, f"Bug {i} missing keys: {missing}"

    def test_no_duplicate_ids(self, bugs):
        ids = [b["bug_id"] for b in bugs]
        assert len(ids) == len(set(ids)), "Duplicate bug_id values"
