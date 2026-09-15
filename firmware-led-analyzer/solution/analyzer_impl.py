
"""
Faithful simulation of both the C (ESP-IDF/FreeRTOS) and Rust (no_std/embassy)
LED command processing pipelines from the neon-beat-buzzer firmware, plus
cross-implementation divergence analysis.
"""

import json
import math


class CProcessor:
    """Simulates the C firmware's LED command processing pipeline.

    Key references (in /app/firmware/c/):
      - ws_commands.c  : JSON parsing, HSV color normalization
      - ubt_led.c      : wave table, blink/wave state machine, timing
      - ubt_led.h      : data structures (led_cmd, color_hsv, led_pattern)
    """

    WAVE_TABLE = [
        0, 16, 31, 47, 63, 78, 93, 108, 122, 136, 149, 162, 174,
        185, 196, 206, 215, 223, 230, 237, 242, 246, 250, 252, 254, 255,
        254, 252, 250, 246, 242, 237, 230, 223, 215, 206, 196, 185, 174,
        162, 149, 136, 122, 108, 93, 78, 63, 47, 31, 16, 0,
    ]

    LED_REFRESH_PERIOD_MS = 20

    def get_wave_table(self):
        """Return the 51-element hardcoded brightness wave table from ubt_led.c."""
        return list(self.WAVE_TABLE)

    def normalize_color(self, h, s, v):
        """Apply C firmware's integer HSV normalization (ws_commands.c).

        C logic:
            hue        = (int)(h > 0 ? h : 360 + h)
            saturation = (int)(s * 255)
            value      = (int)(v * 255)

        Note: C does NOT apply modulo for large positive hue values, and
        treats h == 0.0 as the negative branch (0.0 > 0 is false in C).
        """
        hue = int(h if h > 0 else 360 + h)
        sat = int(s * 255)
        val = int(v * 255)
        return (hue, sat, val)

    def parse_command(self, json_str):
        """Parse a JSON LED command per the C firmware's cJSON logic.

        Returns a dict with keys: pattern, [duration_ms, period_ms, duty_cycle, color]
        or None if the input is invalid.  The 'color' value is an (h, s, v)
        tuple of integers after normalize_color().
        """
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
        """Compute ON/OFF durations per the C blink formula (ubt_led.c).

        C computes each half independently:
            on  = period_ms * duty_cycle / 100
            off = period_ms * (100 - duty_cycle) / 100
        Both use integer division.
        """
        on_ms = period_ms * duty_cycle // 100
        off_ms = period_ms * (100 - duty_cycle) // 100
        return (on_ms, off_ms)

    def compute_wave_cycle_timing(self, duty_cycle):
        """Compute wave cycle parameters per the C wave state machine.

        C source (ubt_led.c) uses:
            tick    = LED_REFRESH_PERIOD_MS (20 ms)
            entries = sizeof(wave) = 51
            pause   = LED_REFRESH_PERIOD_MS * 50 * 100 / duty_cycle
                    = 100000 / duty_cycle  (integer division)

        Note: the constant 50 is hardcoded in the source and differs from
        wave_len (51).
        """
        pause_ms = self.LED_REFRESH_PERIOD_MS * 50 * 100 // duty_cycle
        return {
            "tick_ms": self.LED_REFRESH_PERIOD_MS,
            "num_entries": len(self.WAVE_TABLE),
            "pause_ms": pause_ms,
        }


class RustProcessor:
    """Simulates the Rust firmware's LED command processing pipeline.

    Key references (in /app/firmware/rust/):
      - led_cmd.rs    : JSON parsing (serde), HSV-to-RGB, duty cycle validation
      - led_driver.rs : wave table computation (cosine), blink timing, pattern execution
      - error.rs      : PatternError variants
    """

    MAX_BRIGHTNESS_TABLE_LEN = 70
    WAVE_TICK_PERIOD_MS = 30
    MAX_BRIGHTNESS = 255
    MIN_WAVE_PERIOD_MS = MAX_BRIGHTNESS_TABLE_LEN * WAVE_TICK_PERIOD_MS  # 2100

    def hsv_to_rgb(self, h, s, v):
        """Convert HSV to RGB per the Rust firmware's sector algorithm (led_cmd.rs).

        Rust logic:
            if h < 0:  h = 360 + h
            else:      h = fmod(h, 360)
            c = v * s
            x = c * (1 - |fmod(h/60, 2) - 1|)
            m = v - c
            Select (r,g,b) by 60-degree sector, then scale to 0-255.
        """
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

        r = int((r_tmp + m) * 255.0)
        g = int((g_tmp + m) * 255.0)
        b = int((b_tmp + m) * 255.0)
        return (r, g, b)

    def compute_wave_table(self, period_ms):
        """Compute the 70-entry wave brightness table per led_driver.rs.

        Rust formula for index i in 0..70:
            brightness = trunc(MAX_BRIGHTNESS / 2 * (1 + cos(PI * (2*i - N) / N)))
            duration   = WAVE_TICK_PERIOD_MS (30 ms)

        Last entry (index 69) is overridden:
            brightness = 0
            duration   = period_ms - (N * WAVE_TICK_PERIOD_MS)

        Returns a list of (brightness, duration_ms) tuples.
        """
        N = self.MAX_BRIGHTNESS_TABLE_LEN
        table = []

        for i in range(N):
            value = (
                self.MAX_BRIGHTNESS
                / 2.0
                * (1.0 + math.cos(math.pi * (2.0 * i - N) / N))
            )
            brightness = int(math.trunc(value))
            table.append((brightness, self.WAVE_TICK_PERIOD_MS))

        # Override last entry
        last_duration = period_ms - (N * self.WAVE_TICK_PERIOD_MS)
        table[N - 1] = (0, last_duration)

        return table

    def parse_command(self, json_str):
        """Parse a JSON LED command per the Rust firmware's serde logic.

        Differences from C:
          - Validates dc in [0.0, 1.0]
          - Validates wave period >= MIN_WAVE_PERIOD_MS (2100)
          - Converts HSV to RGB via hsv_to_rgb() instead of storing integer HSV

        Returns a dict with keys: pattern, [duration_ms, period_ms, duty_cycle, color]
        where color is an (r, g, b) tuple, or None if invalid.
        """
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
        # Rust validates: !(0.0..=1.0).contains(&dc) → InvalidDutyCycle
        if not (0.0 <= dc <= 1.0):
            return None

        color = details["color"]
        if not isinstance(color, dict):
            return None
        for key in ("h", "s", "v"):
            if key not in color:
                return None

        # Rust validates wave period
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
        """Compute ON/OFF durations per the Rust blink formula (led_driver.rs).

        Rust computes:
            on  = period * dc / 100
            off = period - on
        This guarantees on + off == period (unlike C's independent division).
        """
        on_ms = period_ms * duty_cycle // 100
        off_ms = period_ms - on_ms
        return (on_ms, off_ms)


def analyze_divergences(json_str):
    """Run both processors on a command and return a structured divergence report.

    The report is a dict whose keys name divergence categories and whose
    values are dicts of specifics.
    """
    c_proc = CProcessor()
    rust_proc = RustProcessor()

    c_proc.parse_command(json_str)
    rust_proc.parse_command(json_str)

    report = {}

    # 1. Wave table divergence
    report["wave_table"] = {
        "c_length": len(c_proc.WAVE_TABLE),
        "rust_length": rust_proc.MAX_BRIGHTNESS_TABLE_LEN,
        "c_source": "hardcoded",
        "rust_source": "computed_cosine",
    }

    # 2. Wave tick period divergence
    report["wave_tick_period"] = {
        "c_ms": c_proc.LED_REFRESH_PERIOD_MS,
        "rust_ms": rust_proc.WAVE_TICK_PERIOD_MS,
    }

    # 3. Color model divergence
    report["color_model"] = {
        "c_model": "hsv_integer",
        "rust_model": "rgb",
        "description": (
            "C stores color as integer HSV (h:0-360, s:0-255, v:0-255) "
            "and passes directly to LED strip API; "
            "Rust converts to RGB (r:0-255, g:0-255, b:0-255) via sector algorithm"
        ),
    }

    # 4. Hue normalization divergence
    report["hue_normalization"] = {
        "c_behavior": "single_negative_wrap",
        "rust_behavior": "negative_wrap_and_positive_modulo",
        "description": (
            "C: h>0 ? h : 360+h — no modulo for positive values, "
            "h=0 maps to 360; "
            "Rust: h<0 ? 360+h : fmod(h,360) — wraps positive values, "
            "h=0 maps to 0"
        ),
    }

    # 5. Duty cycle validation divergence
    report["duty_cycle_validation"] = {
        "c_validates": False,
        "rust_validates": True,
        "rust_valid_range": "0.0 to 1.0",
    }

    # 6. Wave period validation divergence
    report["wave_period_validation"] = {
        "c_validates": False,
        "rust_validates": True,
        "rust_min_period_ms": rust_proc.MIN_WAVE_PERIOD_MS,
    }

    return report
