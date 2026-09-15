
"""Rust-style LED command processing pipeline.

Faithfully reproduces the behavior of the Rust (no_std/embassy) firmware
from the Neon Beat Buzzer project, including the hsv_to_rgb function from
led_cmd.rs, the cosine-based compute_wave_table from led_driver.rs, and
the TryFrom<MessageLedPattern> input validation.
"""

import math
import json


MAX_BRIGHTNESS_TABLE_LEN = 70
WAVE_TICK_PERIOD_MS = 30
MIN_WAVE_PERIOD_MS = MAX_BRIGHTNESS_TABLE_LEN * WAVE_TICK_PERIOD_MS  # 2100
MAX_BRIGHTNESS = 255


def process_hsv(h: float, s: float, v: float) -> tuple:
    """Process HSV the Rust way.

    Exact reimplementation of hsv_to_rgb from led_cmd.rs:53-80.
    Uses float precision throughout (no integer truncation).
    """
    # Rust-style hue preprocessing (led_cmd.rs:54-57)
    if h < 0.0:
        h = 360.0 + h
    else:
        h = math.fmod(h, 360.0)

    c = v * s
    x = c * (1.0 - abs(math.fmod(h / 60.0, 2.0) - 1.0))
    m = v - c

    # Rust uses exclusive upper-bound ranges: 0.0..60.0 means [0, 60)
    if 0.0 <= h < 60.0:
        r, g, b = c, x, 0.0
    elif 60.0 <= h < 120.0:
        r, g, b = x, c, 0.0
    elif 120.0 <= h < 180.0:
        r, g, b = 0.0, c, x
    elif 180.0 <= h < 240.0:
        r, g, b = 0.0, x, c
    elif 240.0 <= h < 300.0:
        r, g, b = x, 0.0, c
    elif 300.0 <= h < 360.0:
        r, g, b = c, 0.0, x
    else:
        # Rust: warn!("Invalid h value!"); returns (0, 0, 0)
        r, g, b = 0.0, 0.0, 0.0

    return (int((r + m) * 255.0), int((g + m) * 255.0), int((b + m) * 255.0))


def generate_wave_table() -> list:
    """Compute the wave table using the Rust formula from led_driver.rs:45-66.

    Formula per entry i:
      value = trunc(MAX_BRIGHTNESS/2 * (1 + cos(pi*(2i - N)/N)))
    where N = MAX_BRIGHTNESS_TABLE_LEN = 70.
    Last entry is forced to 0.
    """
    result = []
    for i in range(MAX_BRIGHTNESS_TABLE_LEN):
        value = MAX_BRIGHTNESS / 2.0 * (
            1.0 + math.cos(
                math.pi * (2.0 * i - MAX_BRIGHTNESS_TABLE_LEN) / MAX_BRIGHTNESS_TABLE_LEN
            )
        )
        result.append(math.trunc(value))

    # Force last entry to 0 (led_driver.rs:61)
    result[MAX_BRIGHTNESS_TABLE_LEN - 1] = 0
    return result


def compute_pattern_timing(period_ms: int, duty_cycle_pct: int, pattern: str) -> dict:
    """Compute pattern timing the Rust way.

    Blink: on = period * dc / 100, off = period - on
    Wave: tick = 30ms, gap = period - TABLE_LEN * TICK_PERIOD, with validation
    """
    dc_float = duty_cycle_pct / 100.0

    if pattern == "blink":
        if dc_float < 0.0 or dc_float > 1.0:
            return {"error": "invalid duty cycle"}
        on_ms = period_ms * duty_cycle_pct // 100
        off_ms = period_ms - on_ms
        return {
            "on_ms": on_ms,
            "off_ms": off_ms,
            "total_cycle_ms": period_ms,
        }
    elif pattern == "wave":
        if dc_float < 0.0 or dc_float > 1.0:
            return {"error": "invalid duty cycle"}
        if period_ms < MIN_WAVE_PERIOD_MS:
            return {"error": f"wave period too short (minimum: {MIN_WAVE_PERIOD_MS}ms)"}
        wave_phase_ms = MAX_BRIGHTNESS_TABLE_LEN * WAVE_TICK_PERIOD_MS
        gap_ms = period_ms - wave_phase_ms
        return {
            "tick_ms": WAVE_TICK_PERIOD_MS,
            "table_entries": MAX_BRIGHTNESS_TABLE_LEN,
            "wave_phase_ms": wave_phase_ms,
            "gap_ms": gap_ms,
            "total_cycle_ms": period_ms,
        }
    elif pattern == "off":
        return {"total_cycle_ms": 0}
    else:
        return {"error": f"invalid pattern type: {pattern}"}


def process_command(json_str: str) -> dict:
    """Parse a JSON command the Rust way (serde deserialization + TryFrom)."""
    data = json.loads(json_str)
    pattern = data.get("pattern", {})
    ptype = pattern.get("type", "")

    if ptype == "off":
        return {"pattern": "off"}

    if ptype not in ("blink", "wave"):
        return {"error": "invalid pattern type"}

    details = pattern.get("details")
    if details is None:
        return {"error": "missing details"}

    dc = details.get("dc", 0)
    if dc < 0.0 or dc > 1.0:
        return {"error": "invalid duty cycle"}

    color = details.get("color", {})
    h = color.get("h", 0.0)
    s_val = color.get("s", 0.0)
    v_val = color.get("v", 0.0)

    rgb = process_hsv(h, s_val, v_val)

    return {
        "pattern": ptype,
        "rgb": rgb,
        "duration_ms": details.get("duration_ms", 0),
        "period_ms": details.get("period_ms", 0),
        "duty_cycle": int(dc * 100),
    }
