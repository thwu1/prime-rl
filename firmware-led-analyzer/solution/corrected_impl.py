
"""
Corrected Python simulation of the neon-beat-buzzer LED firmware.
Faithfully replicates both C and Rust implementations' exact numerical behavior.
"""

import json
import math


class CProcessor:
    """Simulates the C firmware's LED command processing pipeline."""

    WAVE_TABLE = [
        0, 16, 31, 47, 63, 78, 93, 108, 122, 136, 149, 162, 174,
        185, 196, 206, 215, 223, 230, 237, 242, 246, 250, 252, 254, 255,
        254, 252, 250, 246, 242, 237, 230, 223, 215, 206, 196, 185, 174,
        162, 149, 136, 122, 108, 93, 78, 63, 47, 31, 16, 0,
    ]

    LED_REFRESH_PERIOD_MS = 20

    def get_wave_table(self):
        return list(self.WAVE_TABLE)

    def normalize_color(self, h, s, v):
        # C code: (int)(h > 0 ? h : 360 + h)
        # Note: 0.0 > 0 is false in C, so h=0 maps to 360
        hue = int(h if h > 0 else 360 + h)
        sat = int(s * 255)
        val = int(v * 255)
        return (hue, sat, val)

    def parse_command(self, json_str):
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None

        pattern = data.get("pattern")
        if not pattern or not isinstance(pattern, dict):
            return None

        ptype = pattern.get("type")
        if not isinstance(ptype, str):
            return None

        if ptype == "off":
            return {"pattern": "off"}

        if ptype not in ("blink", "wave"):
            return None

        details = pattern.get("details")
        if not details or not isinstance(details, dict):
            return None

        for key in ("duration_ms", "period_ms", "dc", "color"):
            if key not in details:
                return None

        color = details["color"]
        if not isinstance(color, dict):
            return None
        for key in ("h", "s", "v"):
            if key not in color:
                return None
            if not isinstance(color[key], (int, float)):
                return None

        hue, sat, val = self.normalize_color(color["h"], color["s"], color["v"])
        duty_cycle = int(details["dc"] * 100)

        return {
            "pattern": ptype,
            "duration_ms": details["duration_ms"],
            "period_ms": details["period_ms"],
            "duty_cycle": duty_cycle,
            "color": (hue, sat, val),
        }

    def compute_blink_timing(self, period_ms, duty_cycle):
        on_ms = period_ms * duty_cycle // 100
        off_ms = period_ms * (100 - duty_cycle) // 100
        return (on_ms, off_ms)

    def compute_wave_cycle_timing(self, duty_cycle):
        # C source: LED_REFRESH_PERIOD_MS * 50 * 100 / duty_cycle
        # The constant 50 is hardcoded, distinct from wave_len (sizeof(wave) = 51)
        pause_ms = self.LED_REFRESH_PERIOD_MS * 50 * 100 // duty_cycle
        return {
            "tick_ms": self.LED_REFRESH_PERIOD_MS,
            "num_entries": len(self.WAVE_TABLE),
            "pause_ms": pause_ms,
        }


class RustProcessor:
    """Simulates the Rust firmware's LED command processing pipeline."""

    MAX_BRIGHTNESS_TABLE_LEN = 70
    WAVE_TICK_PERIOD_MS = 30
    MAX_BRIGHTNESS = 255
    MIN_WAVE_PERIOD_MS = MAX_BRIGHTNESS_TABLE_LEN * WAVE_TICK_PERIOD_MS

    def hsv_to_rgb(self, h, s, v):
        if h < 0.0:
            h = 360.0 + h
        else:
            h = math.fmod(h, 360.0)

        c = v * s
        x = c * (1.0 - abs(math.fmod(h / 60.0, 2.0) - 1.0))
        m = v - c

        if 0.0 <= h < 60.0:
            r_tmp, g_tmp, b_tmp = c, x, 0.0
        elif 60.0 <= h < 120.0:
            r_tmp, g_tmp, b_tmp = x, c, 0.0
        elif 120.0 <= h < 180.0:
            r_tmp, g_tmp, b_tmp = 0.0, c, x
        elif 180.0 <= h < 240.0:
            r_tmp, g_tmp, b_tmp = 0.0, x, c
        elif 240.0 <= h < 300.0:
            r_tmp, g_tmp, b_tmp = x, 0.0, c
        elif 300.0 <= h < 360.0:
            r_tmp, g_tmp, b_tmp = c, 0.0, x
        else:
            r_tmp, g_tmp, b_tmp = 0.0, 0.0, 0.0

        # Rust uses 'as u8' which truncates (equivalent to int() for positives)
        r = int((r_tmp + m) * 255.0)
        g = int((g_tmp + m) * 255.0)
        b = int((b_tmp + m) * 255.0)
        return (r, g, b)

    def compute_wave_table(self, period_ms):
        N = self.MAX_BRIGHTNESS_TABLE_LEN
        table = []

        for i in range(N):
            # Rust: cos(PI * (2.0 * index - N) / N)
            value = (
                self.MAX_BRIGHTNESS
                / 2.0
                * (1.0 + math.cos(math.pi * (2.0 * i - N) / N))
            )
            brightness = int(math.trunc(value))
            table.append((brightness, self.WAVE_TICK_PERIOD_MS))

        # Rust: period - Duration::from_millis(N * WAVE_TICK_PERIOD_MS)
        last_duration = period_ms - (N * self.WAVE_TICK_PERIOD_MS)
        table[N - 1] = (0, last_duration)

        return table

    def parse_command(self, json_str):
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None

        pattern = data.get("pattern")
        if not pattern or not isinstance(pattern, dict):
            return None

        ptype = pattern.get("type")
        if not isinstance(ptype, str):
            return None

        if ptype == "off":
            return {"pattern": "off"}

        if ptype not in ("blink", "wave"):
            return None

        details = pattern.get("details")
        if not details or not isinstance(details, dict):
            return None

        for key in ("duration_ms", "period_ms", "dc", "color"):
            if key not in details:
                return None

        dc = details["dc"]
        if not isinstance(dc, (int, float)):
            return None
        if not (0.0 <= dc <= 1.0):
            return None

        color = details["color"]
        if not isinstance(color, dict):
            return None
        for key in ("h", "s", "v"):
            if key not in color:
                return None

        if ptype == "wave":
            if details["period_ms"] < self.MIN_WAVE_PERIOD_MS:
                return None

        rgb = self.hsv_to_rgb(color["h"], color["s"], color["v"])
        duty_cycle = int(dc * 100.0)

        return {
            "pattern": ptype,
            "duration_ms": details["duration_ms"],
            "period_ms": details["period_ms"],
            "duty_cycle": duty_cycle,
            "color": rgb,
        }

    def compute_blink_timing(self, period_ms, duty_cycle):
        # Rust: on = period * dc / 100; off = period - on
        on_ms = period_ms * duty_cycle // 100
        off_ms = period_ms - on_ms
        return (on_ms, off_ms)


def analyze_divergences(json_str):
    """Run both processors on a command and return a structured divergence report."""
    c_proc = CProcessor()
    rust_proc = RustProcessor()

    c_proc.parse_command(json_str)
    rust_proc.parse_command(json_str)

    report = {}

    report["wave_table"] = {
        "c_length": len(c_proc.WAVE_TABLE),
        "rust_length": rust_proc.MAX_BRIGHTNESS_TABLE_LEN,
        "c_source": "hardcoded",
        "rust_source": "computed_cosine",
    }

    report["wave_tick_period"] = {
        "c_ms": c_proc.LED_REFRESH_PERIOD_MS,
        "rust_ms": rust_proc.WAVE_TICK_PERIOD_MS,
    }

    report["color_model"] = {
        "c_model": "hsv_integer",
        "rust_model": "rgb",
    }

    report["hue_normalization"] = {
        "c_behavior": "single_negative_wrap",
        "rust_behavior": "negative_wrap_and_positive_modulo",
    }

    report["duty_cycle_validation"] = {
        "c_validates": False,
        "rust_validates": True,
        "rust_valid_range": "0.0 to 1.0",
    }

    report["wave_period_validation"] = {
        "c_validates": False,
        "rust_validates": True,
        "rust_min_period_ms": rust_proc.MIN_WAVE_PERIOD_MS,
    }

    return report
